import re
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.l10n_ro_edi_stock_extension.models.etransport_constants import is_outgoing, is_national


def _unit_value(owner, move, operation):
    """VAT-exclusive RON per declared UoM, with discount and one FX conversion."""
    owner.ensure_one()
    company = owner.company_id
    product = move.product_id.with_company(company)
    source = owner.l10n_ro_edi_stock_price_source or "auto"
    if source == "auto":
        source = "sale" if is_outgoing(operation) or (is_national(operation) and move.picking_type_id.code == "outgoing") else "cost"
    line = move.sale_line_id if source == "sale" else move.purchase_line_id if source == "purchase" else False
    if source == "cost" and not product.standard_price:
        line = move.purchase_line_id
    if line:
        quantity = line.product_uom_qty if line._name == "sale.order.line" else line.product_qty
        if quantity:
            price = line.price_subtotal / quantity
            currency = line.currency_id
            price = currency._convert(price, company.currency_id, company,
                                      fields.Date.to_date(owner.scheduled_date) or fields.Date.context_today(owner), round=False)
            return line.product_uom_id._compute_price(price, move.product_uom)
    if source in ("cost", "purchase"):
        price = abs(move.price_unit) if move.state == "done" and move.price_unit else product.standard_price
    else:
        price = product.list_price
        taxes = product.taxes_id.filtered(lambda t: t.company_id == company)
        if taxes:
            price = taxes.compute_all(price, currency=company.currency_id, quantity=1, product=product)["total_excluded"]
    return product.uom_id._compute_price(price, move.product_uom)


class Product(models.Model):
    _inherit = "product.template"
    gt_etransport_nc = fields.Char("Cod NC / HS e-Transport", size=8,
                                  help="Cod tarifar de 4, 6 sau 8 cifre; folosit dacă produsul nu are cod Intrastat.")

    @api.constrains("gt_etransport_nc")
    def _check_nc(self):
        for product in self:
            if product.gt_etransport_nc and not re.fullmatch(r"(?:\d{4}|\d{6}|\d{8})", product.gt_etransport_nc):
                raise ValidationError("Codul NC / HS trebuie să conțină 4, 6 sau 8 cifre.")


class Picking(models.Model):
    _inherit = "stock.picking"

    def _l10n_ro_edi_stock_get_codtarifar(self, product):
        return super()._l10n_ro_edi_stock_get_codtarifar(product) or product.gt_etransport_nc or None

    def _l10n_ro_edi_stock_compute_value(self, move, op_type):
        return _unit_value(self, move, op_type)


class Batch(models.Model):
    _inherit = "stock.picking.batch"

    def _l10n_ro_edi_stock_compute_value(self, move, op_type):
        return _unit_value(self, move, op_type)


class TransportCompanyMixin(models.AbstractModel):
    _name = "gt.transport.company.mixin"
    _description = "Firma documentului e-Transport"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", compute="_compute_transport_company", store=True, index=True)

    @api.depends("picking_id.company_id", "batch_id.company_id")
    def _compute_transport_company(self):
        for row in self:
            row.company_id = row.picking_id.company_id or row.batch_id.company_id

    @api.constrains("picking_id", "batch_id", "company_id")
    def _check_transport_owner(self):
        for row in self:
            if bool(row.picking_id) == bool(row.batch_id):
                raise ValidationError("Documentul trebuie legat de un transfer sau de un lot, exact unul.")
            target = row.picking_id or row.batch_id
            target.check_access("write")
            if row.company_id not in self.env.companies:
                raise AccessError("Firma documentului nu este în firmele active.")


class DocumentLine(models.Model):
    _name = "l10n.ro.edi.stock.document.line"
    _inherit = ["l10n.ro.edi.stock.document.line", "gt.transport.company.mixin"]


class PreviousNotification(models.Model):
    _name = "l10n.ro.edi.stock.previous.notification"
    _inherit = ["l10n.ro.edi.stock.previous.notification", "gt.transport.company.mixin"]


class ActionWizard(models.TransientModel):
    _inherit = "l10n.ro.edi.stock.action.wizard"

    def action_execute(self):
        self.ensure_one()
        if bool(self.picking_id) == bool(self.batch_id):
            raise ValidationError("Selectați exact un transfer sau un lot.")
        record = self._l10n_ro_edi_stock_record()
        record.check_access("write")
        if record.company_id not in self.env.companies:
            raise AccessError("Firma transferului nu este în firmele active.")
        if not self.uit or self.uit != record.l10n_ro_edi_stock_document_uit:
            raise ValidationError("UIT-ul nu corespunde transferului. Redeschideți operația.")
        return super().action_execute()


class ListWizard(models.TransientModel):
    _inherit = "l10n.ro.edi.stock.list.wizard"

    def action_fetch(self):
        self.ensure_one()
        self.check_access("write")
        if self.company_id not in self.env.companies:
            raise AccessError("Firma interogată nu este în firmele active.")
        return super().action_fetch()


class TransporterWizard(models.TransientModel):
    _inherit = "l10n.ro.edi.stock.transporter.info.wizard"

    def action_fetch(self):
        self.ensure_one()
        self.check_access("write")
        if self.company_id not in self.env.companies:
            raise AccessError("Firma interogată nu este în firmele active.")
        return super().action_fetch()
