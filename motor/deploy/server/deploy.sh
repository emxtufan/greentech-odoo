#!/usr/bin/env bash
# Deploy automat: cod din git -> server nativ (Ubuntu). Se ruleaza ca root.
# Iesire: "Nimic nou" sau "DEPLOY_OK <commit> (-i: ... | -u: ...)".
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

LOCK=/run/greentech-deploy.lock
INSTALL_LIST=$REPO/motor/deploy/server/install-modules.txt
FIRST=${FIRST:-0}
TS=""
OLD=""
NEW=""

mesaj_rollback() {
    echo "EROARE. Revenire: $REPO/motor/deploy/server/rollback.sh $TS" >&2
}

pastreaza_ultimele() {
    local pattern=$1
    local numar=0
    local fisier
    while IFS= read -r fisier; do
        numar=$((numar + 1))
        if [ "$numar" -gt 10 ]; then
            rm -f -- "$fisier"
        fi
    done < <(find "$BK" -maxdepth 1 -type f -name "$pattern" -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
}

face_backup() {
    TS=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$BK" "$DATA/filestore"
    echo "Backup in $BK (identificator $TS) ..."
    runuser -u postgres -- pg_dump -Fc -d "$DB" > "$BK/$DB-$TS.dump"
    tar czf "$BK/filestore-$TS.tar.gz" -C "$DATA/filestore" "$DB"
    echo "$OLD" > "$BK/commit-$TS.txt"
    pastreaza_ultimele "$DB-*.dump"
    pastreaza_ultimele "filestore-*.tar.gz"
    pastreaza_ultimele "commit-*.txt"
}

module_schimbate() {
    local -a gasite=()
    local linie rest repo name cale lista_diff
    if [ "$FIRST" = "1" ]; then
        while IFS= read -r cale; do
            gasite+=("$(basename "$cale")")
        done < <(find "$REPO/module" -mindepth 2 -maxdepth 2 -name __manifest__.py -printf '%h\n' 2>/dev/null | sort)
        for repo in "${OCA_DIRS[@]}"; do
            while IFS= read -r cale; do
                gasite+=("$(basename "$cale")")
            done < <(find "$REPO/motor/third_party_addons/$repo" -mindepth 2 -maxdepth 2 -name __manifest__.py -printf '%h\n' 2>/dev/null | sort)
        done
    else
        lista_diff=$(git -C "$REPO" diff --name-only "$OLD" "$NEW" -- module motor/third_party_addons)
        while IFS= read -r linie; do
            if [ -z "$linie" ]; then
                continue
            fi
            case "$linie" in
                module/*/*)
                    rest=${linie#module/}
                    name=${rest%%/*}
                    if [ -f "$REPO/module/$name/__manifest__.py" ]; then
                        gasite+=("$name")
                    fi
                    ;;
                motor/third_party_addons/*/*)
                    rest=${linie#motor/third_party_addons/}
                    repo=${rest%%/*}
                    rest=${rest#*/}
                    name=${rest%%/*}
                    case " ${OCA_DIRS[*]} " in
                        *" $repo "*)
                            if [ -f "$REPO/motor/third_party_addons/$repo/$name/__manifest__.py" ]; then
                                gasite+=("$name")
                            fi
                            ;;
                    esac
                    ;;
            esac
        done <<< "$lista_diff"
    fi
    if [ "${#gasite[@]}" -gt 0 ]; then
        printf '%s\n' "${gasite[@]}" | sort -u | paste -sd, -
    fi
}

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

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "EROARE: un alt deploy ruleaza deja ($LOCK)." >&2
    exit 1
fi

if [ ! -d "$REPO/.git" ]; then
    echo "EROARE: $REPO nu este depozit git. Ruleaza bootstrap-git.sh." >&2
    exit 1
fi

cd "$REPO"
OLD=$(git rev-parse HEAD)
echo "Verific origin/$BRANCH ..."
git fetch origin "$BRANCH"
NEW=$(git rev-parse "origin/$BRANCH")

if [ "$OLD" = "$NEW" ] && [ "$FIRST" != "1" ]; then
    echo "Nimic nou"
    exit 0
fi

face_backup

echo "Trec pe codul din commit-ul $NEW ..."
git reset --hard "$NEW"

CHANGED=$(module_schimbate)

if ! INSTALATE=$(runuser -u postgres -- psql -d "$DB" -Atc "select name from ir_module_module where state='installed'"); then
    echo "EROARE: nu pot citi modulele instalate din baza $DB." >&2
    exit 1
fi

UPD=""
if [ -n "$CHANGED" ]; then
    IFS=',' read -r -a schimbate <<< "$CHANGED"
    for name in "${schimbate[@]}"; do
        if printf '%s\n' "$INSTALATE" | grep -qxF "$name"; then
            UPD="${UPD:+$UPD,}$name"
        fi
    done
fi

INS=""
if [ -f "$INSTALL_LIST" ]; then
    while IFS= read -r linie || [ -n "$linie" ]; do
        linie=${linie%%#*}
        linie=${linie//[[:space:]]/}
        if [ -z "$linie" ]; then
            continue
        fi
        if printf '%s\n' "$INSTALATE" | grep -qxF "$linie"; then
            continue
        fi
        case ",$INS," in
            *",$linie,"*)
                continue
                ;;
        esac
        INS="${INS:+$INS,}$linie"
    done < "$INSTALL_LIST"
else
    echo "ATENTIE: lipseste $INSTALL_LIST; nu instalez module noi." >&2
fi

if [ -n "$UPD" ] || [ -n "$INS" ]; then
    comanda=(-c "$CONF" -d "$DB" --no-http --stop-after-init)
    if [ -n "$INS" ]; then
        comanda+=(-i "$INS")
    fi
    if [ -n "$UPD" ]; then
        comanda+=(-u "$UPD")
    fi
    echo "Opreste serviciul $SVC ..."
    systemctl stop "$SVC"
    echo "Instalez: ${INS:--}; actualizez: ${UPD:--}"
    if ! runuser -u "$USR" -- "$PY" "$ODOO" "${comanda[@]}"; then
        if ! systemctl start "$SVC"; then
            echo "ATENTIE: serviciul $SVC nu a pornit." >&2
        fi
        mesaj_rollback
        exit 1
    fi
    systemctl start "$SVC"
else
    echo "Cod actualizat, niciun modul de actualizat"
fi

if [ -n "$INS" ]; then
    if ! DUPA=$(runuser -u postgres -- psql -d "$DB" -Atc "select name from ir_module_module where state='installed'"); then
        echo "EROARE: nu pot reciti modulele instalate din baza $DB." >&2
        exit 1
    fi
    LIPSA=""
    IFS=',' read -r -a cerute <<< "$INS"
    for modul in "${cerute[@]}"; do
        if printf '%s\n' "$DUPA" | grep -qxF "$modul"; then
            continue
        fi
        LIPSA="${LIPSA:+$LIPSA,}$modul"
    done
    if [ -n "$LIPSA" ]; then
        conditie=$(printf '%s' "$LIPSA" | sed "s/,/','/g")
        echo "EROARE: module neinstalate: $LIPSA (dependente lipsa sau biblioteci Python lipsa). Verifica: runuser -u postgres -- psql -d $DB -Atc \"select name,state from ir_module_module where name in ('$conditie')\"" >&2
        exit 1
    fi
fi

if ! verifica_health; then
    mesaj_rollback
    exit 1
fi

echo "$NEW" > "$DATA/DEPLOYED_COMMIT"
echo "DEPLOY_OK $NEW (-i: $INS | -u: $UPD)"
