"""Local HTTP/RPC helper for the isolated, fictional Odoo walkthrough."""
import json
import sys
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self):
        self.credentials = json.loads((ROOT / 'config/acces-workflow-test.json').read_text())
        if self.credentials['database'] != 'greentech_flux_test':
            raise RuntimeError('This script may only modify the isolated demonstration database.')
        self.base = 'http://127.0.0.1:8069'
        self.session = requests.Session()
        self.context = {'lang': 'ro_RO', 'tz': 'Europe/Bucharest', 'tracking_disable': True,
                        'mail_create_nosubscribe': True, 'mail_notify_force_send': False}
        auth = self.rpc('/web/session/authenticate', {
            'db': self.credentials['database'], 'login': self.credentials['login'],
            'password': self.credentials['password']})
        self.uid = auth['uid']
        self.state_file = ROOT / 'logs/workflow-state.json'
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding='utf-8')

    def rpc(self, path, params):
        response = self.session.post(self.base + path,
            json={'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}, timeout=180)
        response.raise_for_status()
        data = response.json()
        if 'error' in data:
            detail = data['error'].get('data', {})
            raise RuntimeError(detail.get('debug') or detail.get('message') or data['error']['message'])
        return data.get('result')

    def call(self, model, method, args=None, kwargs=None, context=None):
        options = dict(kwargs or {})
        options['context'] = {**self.context, **(context or {}), **options.get('context', {})}
        return self.rpc(f'/web/dataset/call_kw/{model}/{method}', {
            'model': model, 'method': method, 'args': args or [], 'kwargs': options})

    def search(self, model, domain, fields, limit=0):
        options = {'fields': fields}
        if limit:
            options['limit'] = limit
        return self.call(model, 'search_read', [domain], options)

    def read(self, model, record_id, fields):
        return self.call(model, 'read', [[record_id]], {'fields': fields})[0]

    def write(self, model, record_id, values):
        return self.call(model, 'write', [[record_id], values])

    def ensure(self, key, model, values):
        if key in self.state:
            return self.state[key]
        created = self.call(model, 'create', [[values]])
        record_id = created[0] if isinstance(created, list) else created
        self.state[key] = record_id
        self.save()
        print(f'Created {key}: {model} #{record_id}', flush=True)
        return record_id

    def ref(self, xmlid):
        module, name = xmlid.split('.', 1)
        rows = self.search('ir.model.data', [('module', '=', module), ('name', '=', name)], ['res_id'])
        if len(rows) != 1:
            raise RuntimeError(f'Cannot resolve {xmlid}')
        return rows[0]['res_id']
