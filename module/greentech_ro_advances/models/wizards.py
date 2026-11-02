from odoo import api, Command, fields, models
from odoo.exceptions import AccessError, UserError
from .advances import advance_kind, open_move


class CreateAdvance(models.TransientModel):
    _name = "gt.advance.create"
    _description = "Factură de avans"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", "Firmă", required=True, default=lambda s: s.env.company)
    kind = fields.Selection([("sale", "Client"), ("purchase", "Furnizor")], required=True, default="sale", string="Tip")
    partner_id = fields.Many2one("res.partner", "Partener", required=True, check_company=True)
    date = fields.Date("Data facturii", required=True, default=fields.Date.context_today)
    ref = fields.Char("Referință / număr factură furnizor")
    currency_id = fields.Many2one(related="company_id.currency_id")
    line_ids = fields.One2many("gt.advance.create.line", "wizard_id", string="Poziții avans")
    created_move_id = fields.Many2one("account.move", readonly=True, check_company=True)

    def action_create(self):
        self.ensure_one()
        self.check_access("write")
        self.env.cr.execute("SELECT id FROM gt_advance_create WHERE id=%s FOR UPDATE", [self.id])
        self.invalidate_recordset(["created_move_id"])
        if self.created_move_id:
            self.created_move_id.check_access("read")
            return open_move(self.created_move_id)
        if self.company_id not in self.env.companies:
            raise AccessError("Firma nu este autorizată.")
        if self.company_id.currency_id.name != "RON" or self.company_id.country_id.code != "RO":
            raise UserError("Asistentul este configurat pentru firme din România, cu moneda RON.")
        if not self.line_ids:
            raise UserError("Adăugați cel puțin o poziție de avans.")
        vals = []
        prefix = "419" if self.kind == "sale" else "409"
        for line in self.line_ids:
            if (not line.account_id.with_company(self.company_id).code.startswith(prefix)
                    or self.company_id not in line.account_id.company_ids or line.amount <= 0):
                raise UserError("Selectați un cont de avans al firmei și o valoare pozitivă.")
            if not line.tax_ids:
                raise UserError("Selectați tratamentul TVA, inclusiv o taxă explicită 0% dacă este cazul.")
            if any(t.company_id != self.company_id or t.type_tax_use != self.kind for t in line.tax_ids):
                raise UserError("Taxele trebuie să aparțină firmei și tipului de operațiune.")
            vals.append(Command.create({
                "name": line.name, "account_id": line.account_id.id, "quantity": 1,
                "price_unit": line.amount, "tax_ids": [Command.set(line.tax_ids.ids)],
                "deductible_amount": 100,
            }))
        move = self.env["account.move"].with_company(self.company_id).create({
            "company_id": self.company_id.id, "partner_id": self.partner_id.id,
            "move_type": "out_invoice" if self.kind == "sale" else "in_invoice",
            "invoice_date": self.date, "date": self.date, "ref": self.ref,
            "gt_advance_managed": True, "invoice_line_ids": vals})
        self.created_move_id = move
        return open_move(move)


class CreateAdvanceLine(models.TransientModel):
    _name = "gt.advance.create.line"
    _description = "Poziție factură de avans"
    _check_company_auto = True

    wizard_id = fields.Many2one("gt.advance.create", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id", store=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    name = fields.Char("Descriere", required=True, default="Avans conform contract")
    account_id = fields.Many2one("account.account", "Cont 409 / 419", required=True, check_company=True)
    amount = fields.Monetary("Preț avans", required=True,
        help="Fără TVA pentru taxe excluse din preț; cu TVA pentru taxe incluse în preț.")
    tax_ids = fields.Many2many("account.tax", string="TVA", check_company=True)


class Allocate(models.TransientModel):
    _name = "gt.advance.allocate"
    _description = "Regularizare avans"
    _check_company_auto = True

    move_id = fields.Many2one("account.move", "Factura finală", required=True, check_company=True)
    company_id = fields.Many2one(related="move_id.company_id", store=True)
    currency_id = fields.Many2one(related="move_id.currency_id")
    candidate_ids = fields.Many2many("account.move.line", compute="_compute_candidates")
    source_id = fields.Many2one("account.move.line", "Poziția facturii de avans", required=True, check_company=True)
    available = fields.Monetary("Disponibil fără TVA", related="source_id.gt_advance_available")
    amount = fields.Monetary("Regularizează fără TVA", required=True)
    applied_line_id = fields.Many2one("account.move.line", readonly=True, check_company=True)

    @api.depends("move_id")
    def _compute_candidates(self):
        for wizard in self:
            move = wizard.move_id
            if not move:
                wizard.candidate_ids = False
                continue
            prefix = "419" if move.is_sale_document() else "409"
            candidates = self.env["account.move.line"].search([
                ("company_id", "=", move.company_id.id), ("parent_state", "=", "posted"),
                ("move_id.commercial_partner_id", "=", move.commercial_partner_id.id),
                ("move_id.move_type", "=", move.move_type), ("currency_id", "=", move.currency_id.id),
                ("account_id.code", "=like", prefix + "%"), ("price_subtotal", ">", 0),
                ("gt_advance_origin_id", "=", False), ("date", "<=", move.date)])
            wizard.candidate_ids = candidates.filtered(lambda l: l.gt_advance_available > 0)

    @api.onchange("source_id")
    def _onchange_source(self):
        self.amount = self.source_id.gt_advance_available

    def action_apply(self):
        self.ensure_one()
        self.check_access("write")
        self.env.cr.execute("SELECT id FROM gt_advance_allocate WHERE id=%s FOR UPDATE", [self.id])
        self.invalidate_recordset(["applied_line_id"])
        if self.applied_line_id:
            self.move_id.check_access("read")
            return open_move(self.move_id)
        move, source = self.move_id, self.source_id
        move.check_access("write")
        source.check_access("read")
        if move.company_id not in self.env.companies:
            raise AccessError("Firma nu este autorizată.")
        if move.state != "draft" or move.move_type not in ("in_invoice", "out_invoice"):
            raise UserError("Selectați o factură finală în ciornă.")
        if source not in self.candidate_ids or self.amount <= 0:
            raise UserError("Selectați un avans disponibil și o sumă pozitivă.")
        if source.currency_id.compare_amounts(self.amount, source.gt_advance_available) > 0:
            raise UserError("Suma depășește disponibilul, inclusiv rezervările în alte ciorne.")
        if move.currency_id != move.company_id.currency_id:
            raise UserError("Asistentul de regularizare acceptă momentan facturi în RON.")
        if not move.invoice_line_ids.filtered(lambda l: not advance_kind(l) and l.price_subtotal > 0):
            raise UserError("Completați mai întâi bunurile sau serviciile facturii finale.")
        previous_lines = move.invoice_line_ids
        move.write({"gt_advance_managed": True, "invoice_line_ids": [Command.create({
            "name": "Regularizare avans %s / %s — %s" % (
                source.move_id.ref or source.move_id.name, source.move_id.invoice_date, source.name),
            "account_id": source.account_id.id, "price_unit": source.price_unit,
            "quantity": -source.quantity * self.amount / source.price_subtotal,
            "discount": source.discount, "tax_ids": [Command.set(source.tax_ids.ids)],
            "deductible_amount": source.deductible_amount, "gt_advance_origin_id": source.id,
        })]})
        move._gt_validate()
        if move.currency_id.compare_amounts(move.amount_total, 0) < 0:
            raise UserError("Regularizarea depășește valoarea facturii finale. Folosiți o regularizare parțială.")
        self.applied_line_id = move.invoice_line_ids - previous_lines
        return open_move(move)
