# Deploy pe server (git → server nativ)

Server: `167.233.202.96` (contabilitate.greentechpro.ro). Cod în `/opt/greentech-financiar/repo`,
serviciu `greentech-financiar`, port intern `127.0.0.1:8070`. Scripturile se rulează **ca root**, pe server.

## Fluxul zilnic

1. Editezi local (în `module\` sau `motor\`), apoi dai commit.
2. Dublu-clic pe `motor\PUBLICA.cmd` (sau `powershell -File motor\scripts\publica.ps1`).
   Scriptul verifică branch-ul `main`, cere `git status` gol, face `git push origin main` și rulează pe server
   `/opt/greentech-financiar/repo/motor/deploy/server/deploy.sh`.
3. Pe server, `deploy.sh`:
   - face backup (bază + fișiere atașate + commit curent) în `/var/backups/greentech-financiar`, ultimele 10 din fiecare;
   - aduce codul la `origin/main` (`git reset --hard`);
   - calculează modulele schimbate (`-u`, doar cele deja instalate) și modulele noi din
     `motor/deploy/server/install-modules.txt` (`-i`);
   - oprește serviciul, rulează Odoo cu `-i` / `-u`, apoi pornește serviciul și așteaptă login-ul (max 60 s).
4. Ieșirea se termină cu `DEPLOY_OK <commit> (-i: … | -u: …)`. Dacă nu s-a schimbat nimic: `Nimic nou`.

Dacă `deploy.sh` raportează `EROARE`, mesajul spune exact ce backup trebuie folosit pentru revenire.

## Prima instalare (o singură dată, pe server, ca root)

```
/opt/greentech-financiar/repo/motor/deploy/server/bootstrap-git.sh git@github.com:FIRMA/REPO.git
```

Scriptul: instalează `git` dacă lipsește, generează cheia de deploy `/root/.ssh/greentech_deploy`
(ed25519), adaugă aliasul `github-greentech` în `/root/.ssh/config`, clonează repo-ul în
`/opt/greentech-financiar/repo`, salvează `odoo.conf` (`.bak-<TS>`), rescrie linia `addons_path`
(sursa Odoo + `repo/module` + cele 8 foldere OCA + vechiul `/opt/greentech-financiar/addons`, ca rezervă),
verifică faptul că toate modulele instalate se găsesc în noul `addons_path` și rulează primul deploy.

La prima rulare se oprește cu codul 2 și afișează cheia publică: o adaugi în
GitHub → repo → **Settings → Deploy keys** (read-only), apoi rulezi din nou scriptul.
Dacă vreun modul instalat nu e găsit, scriptul restaurează `odoo.conf` și se oprește cu codul 3.

## Revenire (rollback)

```
/opt/greentech-financiar/repo/motor/deploy/server/rollback.sh <TS>
```

`<TS>` este identificatorul afișat la deploy (ex. `20260120-101530`) sau din numele fișierelor de backup.
Rollback-ul cere confirmare (`DA`), oprește serviciul, readuce codul la commit-ul salvat, recreează baza
din `pg_dump`, restaurează fișierele atașate, pornește serviciul și verifică login-ul (`ROLLBACK_OK`).

## Ce NU se sincronizează prin git

- **Baza de date** — rămâne pe server; prin git circulă doar codul.
- **Fișierele atașate** (filestore) — rămân în `/var/lib/greentech-financiar`; intră doar în backup/rollback.
- **Parolele și configurația** — `odoo.conf` (inclusiv `db_password` și `admin_passwd`) stă în
  `/etc/greentech-financiar/`, nu în repo; la fel cheile SSH și `.env`/`acces-*.json` locale.
- Sursele Odoo, venv-ul și logurile — instalate separat pe server, în afara repo-ului.
