// Execute the actual OCA widget + Odoo patch implementation with DOM/Owl hooks
// stubbed, and real HTTP ORM calls. This is not a visual browser test.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const credentials = JSON.parse(fs.readFileSync('config/acces-financiar-test.json', 'utf8'));
assert.equal(credentials.database, 'greentech_financiar_test');
let cookie = '';
async function rpc(path, params) {
    const response = await fetch('http://127.0.0.1:8070' + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie },
        body: JSON.stringify({jsonrpc:'2.0',method:'call',params,id:1}),
    });
    const sessionCookie = response.headers.getSetCookie().find(c => c.startsWith('session_id='));
    if (sessionCookie) cookie = sessionCookie.split(';')[0];
    const body = await response.json();
    if (body.error) throw Error(body.error.data?.message || body.error.message);
    return body.result;
}
await rpc('/web/session/authenticate', {db:credentials.database,login:credentials.login,password:credentials.password});
const actions = [];
const pending = new Set();
const orm = {
    call(model, method, args, options = {}) {
        const promise = rpc(`/web/dataset/call_kw/${model}/${method}`, {model,method,args,kwargs:{...options, context:{lang:'ro_RO',...options.context}}});
        pending.add(promise);
        promise.finally(() => pending.delete(promise));
        return promise;
    },
    read(model, ids, fields, options) {
        assert(ids.length && ids.every(id => Number.isInteger(id) && id > 0), 'Invalid ids list');
        return this.call(model, 'read', [ids, fields], options);
    },
};
const services = {orm,action:{doAction:action => actions.push(action)},view:{},dialog:{}};
const sandbox = vm.createContext({
    console,
    Component: class { setup() {} },
    onWillStart() {}, onMounted() {}, useBus() {}, useSubEnv() {}, useState: x => x,
    useService: name => services[name],
    SearchModel: class { constructor() { this.searchDomain = []; } async load() {} },
    DateTimeInput: class {}, SearchBar: class {}, AnnotationDialog: class {},
    parseDate: value => value || null, _t: x => x,
    registry: {category:() => ({add(){}})},
    document: {getElementsByClassName:() => [{classList:{toggle(){}}}],getElementById:() => ({classList:{toggle(){}}})},
});
function load(path) {
    const source = fs.readFileSync(path,'utf8').replace(/^import .*;\r?\n/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,sandbox,{filename:path});
}
load('odoo/addons/web/static/src/core/utils/patch.js');
load('odoo/addons/web/static/src/views/fields/standard_field_props.js');
load('third_party_addons/mis-builder/mis_builder/static/src/components/mis_report_widget.esm.js');
const Widget = vm.runInContext('MisReportWidget',sandbox);
const original = new Widget();
original.props = {name:'id',record:{data:{id:1},resId:1,resModel:'mis.report.instance',context:{}}};
assert.equal(original._instanceId(),undefined, 'Reproduce original Odoo 19 field-props defect');
load('custom_addons/greentech_mis_compat/static/src/mis_report_compat.js');
assert.equal(original._instanceId(),1);
const results = {original_bug_reproduced:true,visual_browser_test:false,reports:[]};
for (const id of [1,2,3]) {
    const widget = new Widget();
    widget.props = {name:'id',record:{data:{id},resId:id,resModel:'mis.report.instance',context:{lang:'ro_RO',allowed_company_ids:[1]}}};
    widget.env = {searchModel:{}};
    widget.setup();
    assert.equal(widget._instanceId(),id);
    assert.equal(widget.context.lang,'ro_RO');
    await widget.willStart();
    await Promise.all([...pending]);
    await widget._onMounted();
    assert(widget.state.mis_report_data.body.length > 0);
    assert(widget.state.mis_report_data.body.every(row => row.cells.every(cell => !String(cell.val_r).startsWith('#'))));
    await widget.refresh();
    await widget.toggle_wide_display();
    const cell = widget.state.mis_report_data.body.flatMap(row => row.cells).find(cell => cell.drilldown_arg);
    assert(cell,'Report must offer drilldown');
    await widget.drilldown({target:{dataset:{drilldown:JSON.stringify(cell.drilldown_arg)}}});
    assert.equal(actions.at(-1).res_model,'account.move.line');
    await widget.displaySettings();
    assert.equal(actions.at(-1).res_id,id);
    await widget.exportXls();
    assert.equal(actions.at(-1).report_type,'xlsx');
    await widget.printPdf();
    assert.equal(actions.at(-1).report_type,'qweb-pdf');
    results.reports.push({id,rows:widget.state.mis_report_data.body.length,initialization:true,refresh:true,drilldown:true,settings:true,xlsx_action:true,print_action:true});
}
for (const [record,value,expected] of [
    [{data:{},resModel:'mis.report.instance',resId:2,context:{}},undefined,2],
    [{data:{},context:{active_model:'mis.report.instance',active_id:3}},undefined,3],
    [{data:{},context:{}},1,1],
]) {
    const widget = new Widget();widget.props={name:'id',record,value};assert.equal(widget._instanceId(),expected);
}
fs.writeFileSync('logs/mis-widget-regression.json',JSON.stringify(results,null,2));
console.log('PASS: original defect reproduced and fixed; all 3 live report widget lifecycles, refresh, drilldown, settings and export actions. DOM/Owl hooks simulated.');
