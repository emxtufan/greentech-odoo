/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

export class D112Node extends Component {
    static template = "greentech_anaf_d112.Node";
    static props = ["node", "schema", "path", "readonly", "change", "add", "remove", "move"];
    static components = { D112Node };
    setup() {
        this.ui = useState({ query: "" });
    }
    get definition() {
        return this.props.schema.types[this.props.schema.tags[this.props.node.tag]];
    }
    get attributes() {
        const q = this.ui.query.toLocaleLowerCase("ro");
        return this.definition.attributes.filter(a => `${a.name} ${a.label}`.toLocaleLowerCase("ro").includes(q));
    }
    get additions() {
        // Repeating groups are constrained by XSD validation, not guessed by the UI.
        return this.definition.children.filter((c, i, all) => all.findIndex(x => x.tag === c.tag) === i);
    }
    title(tag) {
        return this.props.schema.titles[tag] || tag;
    }
    value(name) {
        return this.props.node.attrs[name] ?? "";
    }
    edit = (name, event) => {
        this.props.change(this.props.path, name, event.target.value);
    };
    childPath = index => {
        return [...this.props.path, index];
    };
}

export class D112Editor extends Component {
    static template = "greentech_anaf_d112.Editor";
    static components = { D112Node };
    static props = { ...standardFieldProps };
    setup() {
        this.orm = useService("orm");
        this.ui = useState({ tab: "employer", person: 0, search: "" });
        this.edits = useState({ pending: 0, payload: null });
        this.schema = null;
        onWillStart(async () => {
            this.schema = await this.orm.call("gt.anaf.d112", "editor_schema", []);
        });
    }
    get payload() {
        return this.edits.pending ? this.edits.payload : this.props.record.data[this.props.name];
    }
    get people() {
        const q = this.ui.search.toLocaleLowerCase("ro");
        return (this.payload?.children || []).map((node, index) => ({ node, index }))
            .filter(p => p.node.tag === "asigurat")
            .filter(p => `${p.node.attrs.numeAsig || ""} ${p.node.attrs.prenAsig || ""} ${p.node.attrs.cnpAsig || ""}`.toLocaleLowerCase("ro").includes(q));
    }
    get selected() {
        if (!this.payload?.tag) return null;
        if (this.ui.tab === "signer") return { node: { ...this.payload, children: [] }, path: [] };
        if (this.ui.tab === "employer") {
            const i = this.payload.children.findIndex(n => n.tag === "angajator");
            return i >= 0 ? { node: this.payload.children[i], path: [i] } : null;
        }
        const person = this.people.find(p => p.index === this.ui.person) || this.people[0];
        return person ? { node: person.node, path: [person.index] } : null;
    }
    at(root, path) {
        return path.reduce((node, i) => node.children[i], root);
    }
    async mutate(fn) {
        if (this.props.readonly) return;
        const root = JSON.parse(JSON.stringify(this.payload));
        fn(root);
        // Keep rapid edits together while Odoo serializes onchange calls.
        // Enqueue each update immediately so Save also waits for the last edit.
        this.edits.payload = root;
        this.edits.pending++;
        try {
            await this.props.record.update({ [this.props.name]: root });
        } finally {
            this.edits.pending--;
        }
    }
    change = (path, key, value) => this.mutate(root => {
        const node = this.at(root, path);
        if (value === "") delete node.attrs[key];
        else node.attrs[key] = value;
    });
    empty(tag) {
        const definition = this.schema.types[this.schema.tags[tag]];
        return { tag, attrs: {}, children: definition.children.flatMap(c => Array.from({ length: c.min }, () => this.empty(c.tag))) };
    }
    add = (path, tag) => this.mutate(root => {
        const parent = this.at(root, path);
        // A and B are alternatives; both put optional C/D after their own rows.
        const order = parent.tag === "asigurat"
            ? ["det1", "asiguratA", "asiguratB1", "asiguratB2", "asiguratB3", "asiguratB4",
                "asiguratC", "asiguratD", "asiguratE1", "asiguratE2", "asiguratE3", "asiguratE4"]
            : this.schema.types[this.schema.tags[parent.tag]].children.map(c => c.tag);
        const next = parent.children.findIndex(c => order.indexOf(c.tag) > order.indexOf(tag));
        const at = next < 0 ? parent.children.length : next;
        parent.children.splice(at, 0, this.empty(tag));
        if (!path.length && tag === "asigurat") {
            this.ui.tab = "people";
            this.ui.person = at;
        }
    });
    remove = path => this.mutate(root => {
        if (!path.length) return;
        this.at(root, path.slice(0, -1)).children.splice(path.at(-1), 1);
    });
    move = (path, direction) => this.mutate(root => {
        const children = this.at(root, path.slice(0, -1)).children;
        const i = path.at(-1), j = i + direction;
        if (j >= 0 && j < children.length) [children[i], children[j]] = [children[j], children[i]];
    });
}

registry.category("fields").add("gt_d112_editor", {
    component: D112Editor,
    supportedTypes: ["json"],
});
