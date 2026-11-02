"""Porneste Odoo 19 din motor, cu Python-ul din motor\\.venv. Doar biblioteca standard."""
import configparser
import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
MOTOR = os.path.join(ROOT, 'motor')
VENV_PY = os.path.join(MOTOR, '.venv', 'Scripts', 'python.exe')
ODOO_BIN = os.path.join(MOTOR, 'odoo', 'odoo-bin')
CONF = os.path.join(MOTOR, 'config', 'odoo.conf')
ACCESS = os.path.join(MOTOR, 'config', 'acces-local.json')
WAIT_SECONDS = 120


def same_path(left, right):
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def read_port():
    settings = configparser.RawConfigParser()
    settings.read(CONF, encoding='utf-8-sig')
    try:
        return int(settings.get('options', 'http_port'))
    except (configparser.Error, ValueError):
        return 8069


def read_access():
    try:
        with open(ACCESS, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def open_browser(port):
    access = read_access()
    url = access.get('url') or 'http://127.0.0.1:{0}/odoo?db=greentech_financiar_test'.format(port)
    webbrowser.open(url)
    password = access.get('password')
    if password:
        try:
            subprocess.run(['clip'], input=password, text=True, check=False)
        except OSError:
            pass
    print('Utilizator: admin, parola copiata – CTRL+V')


def wait_and_open(port):
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        if port_open(port):
            open_browser(port)
            return
        time.sleep(1)
    print('[ATENTIE] Odoo nu a raspuns pe portul {0} in {1}s. Vezi eroarea de mai sus.'.format(port, WAIT_SECONDS))


def main(argv):
    if not same_path(sys.executable, VENV_PY):
        if not os.path.exists(VENV_PY):
            print('[EROARE] Nu gasesc Python-ul Odoo: ' + VENV_PY)
            print('Ruleaza 01-INSTALEAZA-SURSE.cmd din motor sau refa folderul motor\\.venv.')
            return 1
        return subprocess.call([VENV_PY, os.path.abspath(__file__)] + list(argv))
    if not os.path.exists(ODOO_BIN):
        print('[EROARE] Nu gasesc sursele Odoo: ' + ODOO_BIN)
        print('Ruleaza 01-INSTALEAZA-SURSE.cmd din motor.')
        return 1
    if not os.path.exists(CONF):
        print('[EROARE] Nu gasesc configurarea: ' + CONF)
        print('Ruleaza 02-CONFIGUREAZA-POSTGRES.cmd din motor.')
        return 1
    port = read_port()
    if port_open(port):
        print('Odoo ruleaza deja pe portul {0}. Deschid browserul.'.format(port))
        open_browser(port)
        return 0
    os.chdir(MOTOR)
    threading.Thread(target=wait_and_open, args=(port,), daemon=True).start()
    print('Pornesc Odoo 19 din ' + MOTOR + ' la http://127.0.0.1:{0}'.format(port))
    print('Lasa fereastra deschisa. Opreste serverul cu CTRL+C.')
    command = [VENV_PY, ODOO_BIN, '-c', CONF, '--dev=xml'] + list(argv)
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        print('Odoo oprit')
        return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
