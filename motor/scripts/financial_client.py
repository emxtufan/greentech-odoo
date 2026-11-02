"""RPC access confined to the financial database on port 8070 (includes real imports)."""
import json
import requests
from workflow_demo_client import Client as WorkflowClient, ROOT


class Client(WorkflowClient):
    def __init__(self):
        self.credentials = json.loads((ROOT / 'config/acces-financiar-test.json').read_text())
        if self.credentials['database'] != 'greentech_financiar_test':
            raise RuntimeError('Financial seed restricted to the test database.')
        self.base = 'http://127.0.0.1:8070'
        self.session = requests.Session()
        self.context = {'lang': 'ro_RO', 'tz': 'Europe/Bucharest', 'tracking_disable': True,
                        'mail_create_nosubscribe': True, 'mail_notify_force_send': False}
        self.uid = self.rpc('/web/session/authenticate', {
            'db': self.credentials['database'], 'login': self.credentials['login'],
            'password': self.credentials['password']})['uid']
        self.state_file = ROOT / 'logs/financial-state.json'
        self.state = json.loads(self.state_file.read_text(encoding='utf-8')) if self.state_file.exists() else {}
