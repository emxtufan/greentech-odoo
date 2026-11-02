/** @odoo-module **/
import {Component, useState} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {standardFieldProps} from "@web/views/fields/standard_field_props";

export class VatJournal extends Component {
    static template = "greentech_ro_vat_journals.Journal";
    static props = {...standardFieldProps};
    setup() {
        this.state = useState({category: "", selected: 0});
        this.action = useService("action");
    }
    get data() { return this.props.record.data[this.props.name]; }
    get columns() {
        return [
            ["base", "Bază"], ["vat", "TVA"], ["total", "Total cu TVA"],
            ["eligible", "TVA exigibilă"], ["nondeductible", "TVA nedeductibilă"],
            ["paid", "Achitat în perioadă"], ["paid_base", "Bază achitată"], ["paid_vat", "TVA achitată"],
            ["unpaid", "Neachitat final"], ["pending_base", "Bază neex."], ["pending_vat", "TVA neex."]
        ];
    }
    get rows() { return (this.data?.rows || []).filter(r => !this.state.category || r.category === this.state.category); }
    get selected() { return this.rows.find(r => r.id === this.state.selected); }
    number(value) { return Number(value || 0).toLocaleString("ro-RO", {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
    category(value) { this.state.category = value; this.state.selected = 0; }
    open(id) {
        return this.action.doAction({type: "ir.actions.act_window", res_model: "account.move",
            res_id: id, views: [[false, "form"]], target: "current"});
    }
}
registry.category("fields").add("gt_vat_journal", {component: VatJournal, supportedTypes: ["json"]});
