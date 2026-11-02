from odoo import fields, models


class GreenTechEquipment(models.Model):
    _name = "greentech.equipment"
    _description = "Echipamente GreenTech (demo)"
    _order = "name"

    name = fields.Char(string="Denumire echipament", required=True)
    serial_number = fields.Char(string="Numar de serie")
    status = fields.Selection(
        selection=[
            ("available", "Disponibil"),
            ("in_use", "In utilizare"),
            ("maintenance", "Mentenanta"),
        ],
        string="Stare",
        default="available",
        required=True,
    )
    notes = fields.Text(string="Observatii")
    active = fields.Boolean(default=True)
