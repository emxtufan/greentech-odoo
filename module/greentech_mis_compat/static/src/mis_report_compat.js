/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { standardFieldProps } from '@web/views/fields/standard_field_props';
import { MisReportWidget } from '@mis_builder/components/mis_report_widget.esm';

// Odoo 19 field widgets receive record/name, not a primitive props.value.
MisReportWidget.props = { ...standardFieldProps, value: { type: Number, optional: true } };

patch(MisReportWidget.prototype, {
    _instanceId() {
        const record = this.props.record;
        const context = record?.context || {};
        const candidates = [
            record?.data?.[this.props.name],
            record?.resModel === 'mis.report.instance' ? record.resId : undefined,
            this.props.value,
            context.active_model === 'mis.report.instance' ? context.active_id : undefined,
        ];
        const id = candidates.find(value => Number.isInteger(value) && value > 0);
        if (!id) {
            throw new Error('Raportul nu are un identificator valid. Deschideți un raport salvat din meniul Rapoarte DEMO.');
        }
        return id;
    },

    get context() {
        return { ...(this.props.record?.context || {}), ...super.context };
    },
});
