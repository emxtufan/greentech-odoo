import { patch } from "@web/core/utils/patch";
import { JournalDashboardGraphField } from "@web/views/fields/journal_dashboard_graph/journal_dashboard_graph_field";

/**
 * GreenTech – recolorează graficele din dashboard-ul de jurnal (Chart.js):
 * linia devine neagru (zinc-900), barele trec în scala de gri.
 */

// Paleta "odoo" (vezi @web/core/colors/colors) în modul bright / dark.
const LINE_HEX_COLORS = new Set(["#875a7b", "#6b3e66"]); // #875A7B / #6B3E66
const LINE_ALPHA_REGEX = /^rgba?\((135,90,123|107,62,102)(?:,([0-9.]+))?\)$/;

const BAR_COLORS = {
    "#dcd0d9": "#71717a",
    "#5a395a": "#71717a",
    "#a5d8d7": "#d4d4d8",
    "#147875": "#d4d4d8",
};

function normalize(color) {
    return color.toLowerCase().replace(/\s+/g, "");
}

function toGreenLineColor(color) {
    const normalized = normalize(color);
    if (LINE_HEX_COLORS.has(normalized)) {
        return "#18181b";
    }
    const rgba = LINE_ALPHA_REGEX.exec(normalized);
    if (rgba) {
        return rgba[2] === undefined ? "#18181b" : `rgba(24,24,27,${rgba[2]})`;
    }
    return color;
}

function toGreenBarColor(color) {
    return BAR_COLORS[normalize(color)] ?? color;
}

function recolor(value, convert) {
    if (Array.isArray(value)) {
        return value.map((item) => recolor(item, convert));
    }
    if (typeof value !== "string") {
        return value;
    }
    return convert(value);
}

function recolorDatasets(config, convert) {
    for (const dataset of config?.data?.datasets ?? []) {
        for (const key of ["borderColor", "backgroundColor"]) {
            if (dataset[key] !== undefined) {
                dataset[key] = recolor(dataset[key], convert);
            }
        }
    }
    return config;
}

patch(JournalDashboardGraphField.prototype, {
    getLineChartConfig() {
        return recolorDatasets(super.getLineChartConfig(), toGreenLineColor);
    },

    getBarChartConfig() {
        return recolorDatasets(super.getBarChartConfig(), toGreenBarColor);
    },
});
