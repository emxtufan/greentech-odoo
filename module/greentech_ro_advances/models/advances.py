from odoo import api, fields, models
from odoo.exceptions import UserError


def advance_kind(line):
    if line.company_id.country_id.code != "RO":
        return False
    code = line.account_id.with_company(line.company_id).code or ""
    return "sale" if code.startswith("419") else "purchase" if code.startswith("409") else False


def invoice_sign(move):
    return -1 if move.move_type in ("in_refund", "out_refund") else 1


def open_move(move):
    return {"type": "ir.actions.act_window", "res_model": "account.move", "res_id": move.id,
            "view_mode": "form", "views": [(False, "form")], "target": "current"}


class MoveLine(models.Model):
    _inherit = "account.move.line"

    gt_advance_origin_id = fields.Many2one(
        "account.move.line", "Linia facturii de avans", check_company=True,
        copy=False, index=True, ondelete="restrict")
    gt_advance_usage_ids = fields.One2many("account.move.line", "gt_advance_origin_id")
    gt_advance_lock_version = fields.Integer(default=0, readonly=True, copy=False)
    gt_advance_available = fields.Monetary("Disponibil fără TVA", compute="_compute_gt_available")
    gt_advance_used = fields.Monetary("Regularizat fără TVA", compute="_compute_gt_available")
    gt_advance_reserved = fields.Monetary("Rezervat în ciorne fără TVA", compute="_compute_gt_available")

    def _gt_is_source(self):
        self.ensure_one()
        return (self.display_type == "product" and advance_kind(self)
                and self.move_id.move_type in ("out_invoice", "in_invoice")
                and not self.gt_advance_origin_id and self.price_subtotal > 0)

    def _gt_usage(self, include_posting=None):
        self.ensure_one()
        posted = reserved = 0.0
        for line in self.gt_advance_usage_ids:
            amount = -invoice_sign(line.move_id) * line.price_subtotal
            if line.move_id.state == "posted" or line.move_id in (include_posting or self.env["account.move"]):
                posted += amount
            elif line.move_id.state == "draft" and amount > 0:
                # A draft refund must not release an advance before it is posted.
                reserved += amount
        return posted, reserved

    @api.depends("price_subtotal", "gt_advance_usage_ids.price_subtotal",
                 "gt_advance_usage_ids.move_id.state", "gt_advance_usage_ids.move_id.move_type")
    def _compute_gt_available(self):
        for line in self:
            used, reserved = line._gt_usage() if line._gt_is_source() else (0, 0)
            line.gt_advance_used = used
            line.gt_advance_reserved = reserved
            line.gt_advance_available = line.price_subtotal - used - reserved if line._gt_is_source() else 0

    def copy_data(self, default=None):
        values = super().copy_data(default)
        if "move_reverse_cancel" in self.env.context:
            for line, vals in zip(self, values):
                origin = line.gt_advance_origin_id or (line if line._gt_is_source() else False)
                if origin:
                    vals["gt_advance_origin_id"] = origin.id
        return values

    def write(self, vals):
        sensitive = {"account_id", "partner_id", "price_unit", "quantity", "discount", "tax_ids",
                     "currency_id", "company_id", "move_id", "gt_advance_origin_id", "deductible_amount"}
        if sensitive.intersection(vals):
            for line in self:
                if line.gt_advance_usage_ids.filtered(lambda l: l.move_id.state != "cancel"):
                    raise UserError("Avansul are regularizări sau rezervări. Anulați-le înainte de modificare.")
                if (line.gt_advance_origin_id or vals.get("gt_advance_origin_id")) and line.move_id.state == "posted":
                    raise UserError("Regularizarea contabilizată se corectează prin stornare.")
        return super().write(vals)


class Move(models.Model):
    _inherit = "account.move"

    gt_advance_managed = fields.Boolean("Control avansuri", copy=False)
    gt_advance_kind = fields.Selection([("sale", "Client"), ("purchase", "Furnizor")],
                                      compute="_compute_gt_advance_kind", store=True, index=True)
    gt_advance_base = fields.Monetary("Avans fără TVA", compute="_compute_gt_amounts")
    gt_advance_used = fields.Monetary("Regularizat fără TVA", compute="_compute_gt_amounts")
    gt_advance_reserved = fields.Monetary("Rezervat fără TVA", compute="_compute_gt_amounts")
    gt_advance_remaining = fields.Monetary("Disponibil fără TVA", compute="_compute_gt_amounts")
    gt_advance_sources = fields.Many2many("account.move.line", compute="_compute_gt_amounts")

    @api.depends("invoice_line_ids.account_id", "move_type")
    def _compute_gt_advance_kind(self):
        for move in self:
            kinds = [advance_kind(l) for l in move.invoice_line_ids if advance_kind(l)]
            move.gt_advance_kind = kinds[0] if move.is_invoice() and kinds else False

    @api.depends("invoice_line_ids.price_subtotal", "invoice_line_ids.gt_advance_origin_id",
                 "invoice_line_ids.gt_advance_available", "invoice_line_ids.gt_advance_used",
                 "invoice_line_ids.gt_advance_reserved")
    def _compute_gt_amounts(self):
        for move in self:
            lines = move.invoice_line_ids.filtered(lambda l: l._gt_is_source())
            move.gt_advance_sources = lines
            move.gt_advance_base = sum(lines.mapped("price_subtotal"))
            move.gt_advance_used = sum(lines.mapped("gt_advance_used"))
            move.gt_advance_reserved = sum(lines.mapped("gt_advance_reserved"))
            move.gt_advance_remaining = sum(lines.mapped("gt_advance_available"))

    def action_gt_regularize(self):
        self.ensure_one()
        if self.state != "draft" or self.move_type not in ("in_invoice", "out_invoice"):
            raise UserError("Regularizarea se adaugă pe o factură finală în ciornă.")
        return {"type": "ir.actions.act_window", "res_model": "gt.advance.allocate",
                "view_mode": "form", "target": "new",
                "context": {"default_move_id": self.id}}

    def action_gt_history(self):
        self.ensure_one()
        lines = self.gt_advance_sources.gt_advance_usage_ids | self.invoice_line_ids.filtered("gt_advance_origin_id")
        moves = lines.move_id | lines.gt_advance_origin_id.move_id | self
        return {"type": "ir.actions.act_window", "name": "Avans și regularizări",
                "res_model": "account.move", "view_mode": "list,form",
                "domain": [("id", "in", moves.ids)]}

    def _gt_link_native_sales(self):
        """Keep native sales down payments in the same audit trail."""
        for move in self.filtered(lambda m: m.state == "draft" and m.move_type == "out_invoice"):
            for line in move.invoice_line_ids.filtered(
                    lambda l: advance_kind(l) and l.price_subtotal < 0 and not l.gt_advance_origin_id):
                sources = line.sale_line_ids.invoice_lines.filtered(
                    lambda l: l.move_id.state == "posted" and l._gt_is_source())
                if len(sources) == 1:
                    line.gt_advance_origin_id = sources.id
                    move.gt_advance_managed = True
                elif sources:
                    raise UserError("Mai multe facturi de avans pentru aceeași linie. Folosiți Regularizează avans.")

    def _gt_validate(self):
        lines = self.invoice_line_ids.filtered("gt_advance_origin_id")
        origins = lines.gt_advance_origin_id
        if origins:
            # Serialize all consumers of an origin. Recheck after obtaining the lock.
            # Odoo uses repeatable-read transactions: a row lock alone does not
            # refresh a competing transaction's snapshot. Changing this private
            # version forces PostgreSQL to serialize/retry concurrent consumers.
            for origin_id in sorted(origins.ids):
                self.env.cr.execute(
                    "UPDATE account_move_line SET gt_advance_lock_version=COALESCE(gt_advance_lock_version,0)+1 WHERE id=%s",
                    [origin_id])
            origins.invalidate_recordset()
        for line in lines:
            source, move = line.gt_advance_origin_id, line.move_id
            source.check_access("read")
            if not source._gt_is_source() or source.move_id.state != "posted":
                raise UserError("Factura de avans sursă trebuie să fie contabilizată.")
            if (source.company_id != move.company_id
                    or source.move_id.commercial_partner_id != move.commercial_partner_id
                    or source.currency_id != move.currency_id
                    or source.account_id != line.account_id
                    or advance_kind(source) != ("sale" if move.is_sale_document() else "purchase")
                    or source.move_id == move):
                raise UserError("Avansul trebuie să aibă aceeași firmă, partener, monedă, cont și direcție.")
            if source.tax_ids != line.tax_ids or source.deductible_amount != line.deductible_amount:
                raise UserError("Stornarea avansului trebuie să păstreze taxele și deductibilitatea sursei.")
            if move.date < source.move_id.date:
                raise UserError("Regularizarea nu poate preceda factura de avans.")
            amount = -invoice_sign(move) * line.price_subtotal
            if amount < 0 and not move.reversed_entry_id:
                raise UserError("Restabilirea unui avans este permisă doar prin stornarea regularizării originale.")
            if amount < 0:
                original_lines = move.reversed_entry_id.invoice_line_ids.filtered(
                    lambda l: l.gt_advance_origin_id == source)
                original_amount = -sum(l.price_subtotal * invoice_sign(l.move_id) for l in original_lines)
                refunds = source.gt_advance_usage_ids.filtered(
                    lambda l: l.move_id.reversed_entry_id == move.reversed_entry_id
                    and (l.move_id.state == "posted" or l.move_id in self))
                restored = sum(max(invoice_sign(l.move_id) * l.price_subtotal, 0) for l in refunds)
                if original_amount <= 0 or source.currency_id.compare_amounts(restored, original_amount) > 0:
                    raise UserError("Stornările depășesc regularizarea facturii originale.")
            if move.currency_id != move.company_id.currency_id:
                # Foreign currency tax-base adjustments need a separately reviewed flow.
                raise UserError("Regularizarea automată este disponibilă în RON. Pentru valută folosiți circuitul contabil verificat separat.")
        for origin in origins:
            used, reserved = origin._gt_usage(include_posting=self)
            currency = origin.currency_id
            if currency.compare_amounts(used + reserved, origin.price_subtotal) > 0 or currency.compare_amounts(used, 0) < 0:
                raise UserError("Valoarea regularizată și rezervată depășește avansul disponibil.")
        for move in self.filtered(lambda m: m.is_invoice()):
            for line in move.invoice_line_ids.filtered(lambda l: advance_kind(l)):
                if (invoice_sign(move) * line.price_subtotal < 0 or move.move_type in ("out_refund", "in_refund")) and not line.gt_advance_origin_id:
                    raise UserError("Selectați factura de avans pentru fiecare linie de regularizare.")

    def _post(self, soft=True):
        self._gt_link_native_sales()
        self._gt_validate()
        return super()._post(soft)

    def button_draft(self):
        origins = self.invoice_line_ids.gt_advance_origin_id
        for move in self:
            uses = move.invoice_line_ids.gt_advance_usage_ids.filtered(lambda l: l.move_id.state != "cancel")
            if uses:
                raise UserError("Avansul este folosit în alte documente. Anulați întâi regularizările și rezervările.")
        result = super().button_draft()
        for origin in origins:
            used, reserved = origin._gt_usage()
            if origin.currency_id.compare_amounts(used + reserved, origin.price_subtotal) > 0 or used < 0:
                raise UserError("Stornarea a fost deja folosită. Corectați întâi documentele ulterioare.")
        return result

    def button_cancel(self):
        for move in self:
            if move.invoice_line_ids.gt_advance_usage_ids.filtered(lambda l: l.move_id.state != "cancel"):
                raise UserError("Nu puteți anula un avans folosit de alte documente.")
        return super().button_cancel()

    def write(self, vals):
        if {"partner_id", "company_id", "currency_id", "move_type", "date", "invoice_date"}.intersection(vals):
            for move in self:
                if move.invoice_line_ids.gt_advance_usage_ids.filtered(lambda l: l.move_id.state != "cancel"):
                    raise UserError("Factura de avans folosită în regularizări nu poate fi modificată.")
        return super().write(vals)


class SaleAdvance(models.TransientModel):
    _inherit = "sale.advance.payment.inv"

    def _prepare_down_payment_invoice_values(self, order, so_lines):
        vals = super()._prepare_down_payment_invoice_values(order, so_lines)
        if order.company_id.country_id.code == "RO":
            account = order.company_id.downpayment_account_id
            if not account:
                account = self.env["account.account"].with_company(order.company_id).search([
                    ("company_ids", "in", order.company_id.id), ("code", "=", "419000")], limit=1)
            if not account or not account.with_company(order.company_id).code.startswith("419"):
                raise UserError("Configurați contul 419 pentru avansurile clienților.")
            vals["gt_advance_managed"] = True
            for command in vals["invoice_line_ids"]:
                if command[0] == 0 and command[2].get("display_type", "product") == "product":
                    command[2]["account_id"] = account.id
        return vals
