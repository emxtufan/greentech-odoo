/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

class D300Report extends Component {
    static template = "greentech_anaf_d300.Report";
    static props = { ...standardFieldProps };
    setup() {
        this.action = useService("action");
        this.ui = useState({ row: "", nonzero: true, query: "" });
    }
    get data() { return this.props.record.data[this.props.name]; }
    get rows() {
        return (this.data?.rows || []).filter(r => (!this.ui.nonzero || r.base || r.tax || ["19","30","31","35","44","45"].includes(r.code))
            && (!this.ui.query || `${r.code} ${r.label}`.toLocaleLowerCase("ro").includes(this.ui.query.toLocaleLowerCase("ro"))));
    }
    get documents() {
        return (this.data?.contributions || []).filter(c => !this.ui.row || c.row === this.ui.row
            || this.data.rows.find(r => r.code === c.row)?.parent === this.ui.row
            || (this.ui.row === "19" && Number(c.row) < 19)
            || (["30", "31"].includes(this.ui.row) && Number(c.row) >= 20 && Number(c.row) <= 28)
            || (this.ui.row === "35" && Number(c.row) >= 20 && Number(c.row) <= 34));
    }
    amount(v) { return Number(v || 0).toLocaleString("ro-RO", {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
    total(code) { return this.data?.rows.find(r => r.code === code)?.tax || 0; }
    select(code) { this.ui.row = this.ui.row === code ? "" : code; }
    open(id) {
        return this.action.doAction({type:"ir.actions.act_window",res_model:"account.move",res_id:id,views:[[false,"form"]],target:"current"});
    }
}
registry.category("fields").add("gt_d300_report", {component: D300Report, supportedTypes:["json"]});
