#!/usr/bin/env bash
# Prima instalare: cheie deploy + clone git + addons_path + primul deploy.
# Utilizare: bootstrap-git.sh <git-ssh-url>   (o singura data, ca root)
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

SSH_DIR=/root/.ssh
SSH_CONFIG=$SSH_DIR/config
CHEIE=$SSH_DIR/greentech_deploy
ALIAS=github-greentech
URL_GIT=${1:-}
TS=""
ADDONS_PATH=""

if [ "$(id -u)" -ne 0 ]; then
    echo "EROARE: ruleaza scriptul ca root." >&2
    exit 1
fi

if [ -z "$URL_GIT" ]; then
    echo "Utilizare: bootstrap-git.sh <git-ssh-url> (ex. git@github.com:firma/repo.git)" >&2
    exit 1
fi

if [ ! -f "$CONF" ]; then
    echo "EROARE: lipseste $CONF. Instaleaza mai intai serverul nativ (instaleaza-financiar-nativ.py)." >&2
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "Instalez git ..."
    apt-get update
    apt-get install -y git
fi

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

if [ ! -f "$CHEIE" ]; then
    echo "Generez cheia de deploy $CHEIE ..."
    ssh-keygen -q -t ed25519 -N "" -f "$CHEIE" -C "deploy@greentech-financiar"
fi
chmod 600 "$CHEIE"

if [ ! -f "$SSH_CONFIG" ]; then
    : > "$SSH_CONFIG"
fi
chmod 600 "$SSH_CONFIG"

if ! grep -q "^Host $ALIAS$" "$SSH_CONFIG"; then
    cat >> "$SSH_CONFIG" <<EOF
Host $ALIAS
    HostName github.com
    User git
    IdentityFile $CHEIE
    IdentitiesOnly yes
EOF
fi

AUTENTIFICARE=$(ssh -o StrictHostKeyChecking=accept-new -T "$ALIAS" 2>&1 || true)
if ! printf '%s' "$AUTENTIFICARE" | grep -q "successfully authenticated"; then
    echo "Cheia publica de adaugat in GitHub:"
    cat "$CHEIE.pub"
    echo "Adaug-o in GitHub -> repo -> Settings -> Deploy keys (read-only), apoi ruleaza din nou."
    exit 2
fi
echo "Autentificare GitHub OK."

CLONE_URL=${URL_GIT/github.com/$ALIAS}
if [ ! -d "$REPO/.git" ]; then
    mkdir -p "$(dirname "$REPO")"
    echo "Clonez $CLONE_URL in $REPO ..."
    git clone "$CLONE_URL" "$REPO"
fi
chmod -R a+rX "$REPO"

TS=$(date +%Y%m%d-%H%M%S)
cp "$CONF" "$CONF.bak-$TS"
echo "Backup configuratie: $CONF.bak-$TS"

ADDONS_PATH="$ROOT/source/odoo/addons,$REPO/module"
for dir_oca in "${OCA_DIRS[@]}"; do
    ADDONS_PATH="$ADDONS_PATH,$REPO/motor/third_party_addons/$dir_oca"
done
ADDONS_PATH="$ADDONS_PATH,$ROOT/addons"

if ! python3 - "$CONF" "$ADDONS_PATH" <<'COD'
import sys

conf, valoare = sys.argv[1], sys.argv[2]
with open(conf, encoding="utf-8") as intrare:
    linii = intrare.readlines()
rezultat = []
gasit = False
for linie in linii:
    if linie.split("=", 1)[0].strip() == "addons_path":
        if not gasit:
            rezultat.append("addons_path = " + valoare + "\n")
            gasit = True
        continue
    rezultat.append(linie)
if not gasit:
    rezultat.append("addons_path = " + valoare + "\n")
with open(conf, "w", encoding="utf-8") as iesire:
    iesire.writelines(rezultat)
COD
then
    cp "$CONF.bak-$TS" "$CONF"
    echo "EROARE: nu am putut scrie addons_path in $CONF. Am restaurat configuratia." >&2
    exit 1
fi
echo "addons_path nou: $ADDONS_PATH"

if ! INSTALATE=$(runuser -u postgres -- psql -d "$DB" -Atc "select name from ir_module_module where state='installed' and name <> 'base'"); then
    cp "$CONF.bak-$TS" "$CONF"
    echo "EROARE: nu pot citi modulele instalate din baza $DB. Am restaurat configuratia." >&2
    exit 1
fi

IFS=',' read -r -a CAI <<< "$ADDONS_PATH"
LIPSA=""
for modul in $INSTALATE; do
    gasit=0
    for cale in "${CAI[@]}"; do
        if [ -f "$cale/$modul/__manifest__.py" ]; then
            gasit=1
            break
        fi
    done
    if [ "$gasit" -eq 0 ]; then
        LIPSA="$LIPSA $modul"
    fi
done

if [ -n "$LIPSA" ]; then
    echo "EROARE: module instalate in baza dar negasite in addons_path nou:$LIPSA" >&2
    cp "$CONF.bak-$TS" "$CONF"
    echo "Am restaurat $CONF din $CONF.bak-$TS." >&2
    exit 3
fi
echo "Toate modulele instalate au fost gasite in addons_path."

echo "Pornesc primul deploy ..."
FIRST=1 bash "$REPO/motor/deploy/server/deploy.sh"
