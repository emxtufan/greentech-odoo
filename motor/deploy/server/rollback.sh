#!/usr/bin/env bash
# Revenire la un backup creat de deploy.sh: baza, filestore si cod.
# Utilizare: rollback.sh <TS>   (ruleaza ca root)
set -euo pipefail

ROOT=/opt/greentech-financiar
REPO=$ROOT/repo
CONF=/etc/greentech-financiar/odoo.conf
DB=greentech_financiar_test
SVC=greentech-financiar
USR=gt_financiar
PY=$ROOT/venv/bin/python
ODOO=$ROOT/source/odoo-bin
DATA=/var/lib/greentech-financiar
BK=/var/backups/greentech-financiar
BRANCH=${BRANCH:-main}
URL=http://127.0.0.1:8070/web/login
OCA_DIRS=(account-financial-reporting account-financial-tools account-reconcile reporting-engine server-ux mis-builder oca-ro-19 bank-statement-import)

TS=${1:-}

verifica_health() {
    local incercare
    for incercare in $(seq 1 30); do
        if curl -fsS -o /dev/null "$URL"; then
            return 0
        fi
        echo "Astept Odoo ($incercare/30) ..."
        sleep 2
    done
    return 1
}

if [ "$(id -u)" -ne 0 ]; then
    echo "EROARE: ruleaza scriptul ca root." >&2
    exit 1
fi

if [ -z "$TS" ]; then
    echo "Utilizare: rollback.sh <TS> (identificatorul afisat la deploy)" >&2
    exit 1
fi

case "$TS" in
    *[!0-9-]*)
        echo "EROARE: identificator invalid: $TS" >&2
        exit 1
        ;;
esac

DUMP=$BK/$DB-$TS.dump
ARHIVA=$BK/filestore-$TS.tar.gz
FISIER_COMMIT=$BK/commit-$TS.txt

for fisier in "$DUMP" "$ARHIVA" "$FISIER_COMMIT"; do
    if [ ! -f "$fisier" ]; then
        echo "EROARE: lipseste $fisier" >&2
        exit 1
    fi
done

COMMIT=$(cat "$FISIER_COMMIT")
echo "Revin la commit-ul $COMMIT si la backupul $TS."
echo "ATENTIE: baza $DB si fisierele atasate vor fi inlocuite cu cele din backup."
printf 'Scrie DA pentru confirmare: '
RASPUNS=""
if ! read -r RASPUNS; then
    RASPUNS=""
fi
if [ "$RASPUNS" != "DA" ]; then
    echo "Anulat."
    exit 0
fi

echo "Opreste serviciul $SVC ..."
systemctl stop "$SVC"

echo "Revin codul la $COMMIT ..."
git -C "$REPO" reset --hard "$COMMIT"

echo "Reconstruiesc baza $DB din backup ..."
runuser -u postgres -- dropdb "$DB"
runuser -u postgres -- createdb -O "$USR" "$DB"
runuser -u postgres -- pg_restore -d "$DB" --no-owner --role="$USR" "$DUMP"

echo "Restabilesc fisierele atasate ..."
rm -rf "$DATA/filestore/$DB"
tar xzf "$ARHIVA" -C "$DATA/filestore"
chown -R "$USR:$USR" "$DATA/filestore/$DB"

echo "Pornesc serviciul $SVC ..."
systemctl start "$SVC"

if ! verifica_health; then
    echo "EROARE: Odoo nu raspunde dupa revenire. Verifica jurnalul serviciului $SVC." >&2
    exit 1
fi

echo "ROLLBACK_OK"
