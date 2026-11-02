"""Interactive, administrator-run password recovery for this local PG18 install."""

import ctypes
import getpass
import os
from pathlib import Path
import sys

import psycopg2
from psycopg2.extensions import encrypt_password


def connect_for_recovery(hba_path, connect):
    """Restore exact original HBA bytes before returning the open connection."""
    backup = hba_path.with_name('pg_hba.conf.greentech-password-recovery.bak')
    if backup.exists():
        hba_path.write_bytes(backup.read_bytes())
        if hba_path.read_bytes() != backup.read_bytes():
            raise RuntimeError('Restaurarea configuratiei anterioare a esuat.')
        backup.unlink()
        raise RuntimeError('Configuratia unei incercari intrerupte a fost restaurata. Ruleaza din nou scriptul.')

    original = hba_path.read_bytes()
    with backup.open('xb') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    connection = None
    try:
        # Windows applies HBA changes to new connections without a service restart.
        # Only the local postgres role connecting to the postgres database is allowed.
        prefix = b'host postgres postgres 127.0.0.1/32 trust\r\n'
        hba_path.write_bytes(prefix + original.removeprefix(b'\xef\xbb\xbf'))
        connection = connect()
    finally:
        try:
            hba_path.write_bytes(original)
            if hba_path.read_bytes() != original:
                raise RuntimeError('Verificarea restaurarii pg_hba.conf a esuat.')
            backup.unlink()
        except Exception:
            if connection is not None:
                connection.close()
            print('ATENTIE: restaurarea automata a esuat!', file=sys.stderr)
            print(f'Copiaza {backup} peste {hba_path} inainte de a continua.', file=sys.stderr)
            raise
    return connection


def main():
    print('=== Resetare parola PostgreSQL 18 / cont postgres ===')
    if os.name != 'nt' or not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('Click dreapta pe 02A-RESETEAZA-PAROLA-POSTGRES.cmd -> Run as administrator.')

    hba_path = Path(r'C:\Program Files\PostgreSQL\18\data\pg_hba.conf')
    if not hba_path.is_file():
        raise RuntimeError(f'Nu gasesc configuratia asteptata: {hba_path}')

    print('Bazele de date sunt pastrate. Se schimba doar parola rolului postgres.')
    print('Alege si pastreaza noua parola. Nu apare pe ecran cand o tastezi.')
    print('Nu inchide fereastra in timpul operatiei.')
    password = getpass.getpass('Parola NOUA: ')
    if not password:
        raise RuntimeError('Parola nu poate fi goala. Nu am modificat nimic.')
    if password != getpass.getpass('Repeta parola NOUA: '):
        raise RuntimeError('Parolele nu coincid. Nu am modificat nimic.')

    parameters = dict(host='127.0.0.1', port=5432, user='postgres',
                      dbname='postgres', connect_timeout=5,
                      application_name='greentech_local_password_recovery')
    connection = connect_for_recovery(
        hba_path, lambda: psycopg2.connect(**parameters, password=''))
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('SHOW hba_file')
            active_hba = Path(cursor.fetchone()[0])
            if active_hba.resolve() != hba_path.resolve():
                raise RuntimeError('Instanta foloseste alta configuratie. Parola nu a fost schimbata.')
            # Encrypt on the client so the clear password never enters SQL/logs.
            encrypted = encrypt_password(password, 'postgres', connection, algorithm='scram-sha-256')
            cursor.execute('ALTER ROLE postgres PASSWORD %s', (encrypted,))
    finally:
        connection.close()

    verification = psycopg2.connect(**parameters, password=password)
    try:
        with verification.cursor() as cursor:
            cursor.execute('SELECT current_user')
            if cursor.fetchone()[0] != 'postgres':
                raise RuntimeError('Verificarea contului a esuat.')
    finally:
        verification.close()
        password = None

    print('\nGATA: parola a fost schimbata si conexiunea noua a fost verificata.')
    print('Configuratia originala de autentificare a fost restaurata.')
    print('1. Inchide aceasta fereastra.')
    print('2. Ruleaza normal 02-CONFIGUREAZA-POSTGRES.cmd cu parola NOUA.')
    print('3. Ruleaza 03-PORNESTE-ODOO.cmd.')
    print('4. Deschide http://127.0.0.1:8069')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nOperatie intrerupta. Daca ai inchis fortat o incercare, ruleaza din nou scriptul pentru restaurare.')
        sys.exit(1)
    except Exception as exc:
        # Do not print connection/SQL details that could contain password material.
        if isinstance(exc, psycopg2.Error):
            print(f'EROARE PostgreSQL ({type(exc).__name__}). Resetarea nu este confirmata.')
        else:
            print(f'EROARE: {exc}')
        sys.exit(1)
