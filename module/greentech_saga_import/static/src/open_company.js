/** @odoo-module **/
import { registry } from "@web/core/registry";
import { cookie } from "@web/core/browser/cookie";
import { browser } from "@web/core/browser/browser";

// Reload also refreshes the allowed-company list after an initial import.
registry.category("actions").add("greentech_saga_open_company", (env, action) => {
    const company = Number(action.params.company_id);
    const target = Number(action.params.action_id);
    if (!Number.isSafeInteger(company) || company <= 0 || !Number.isSafeInteger(target) || target <= 0) {
        throw new Error("Firma sau ecranul solicitat nu este valid.");
    }
    cookie.set("cids", String(company));
    browser.location.assign(`/odoo/action-${target}`);
});
