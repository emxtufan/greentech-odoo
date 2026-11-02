# Plan

## Obiectiv

Editări locale → git (GitHub privat) → deploy pe server 167.233.202.96 (contabilitate.greentechpro.ro), cu actualizare automată a modulelor.

## Decizii

- În git intră: `module/` (module custom), `motor/third_party_addons/` (OCA vendored), `motor/deploy`, `motor/scripts`, launcher-e.
- În git NU intră: sursa Odoo (`motor/odoo` — serverul are `/opt/greentech-financiar/source`), venv, date, loguri, configuri cu parole.
- Istorie git nouă (branch orfan `main`), fiindcă primul commit din `master` conține parole.
- Datele (baza) NU se sincronizează prin git: serverul își păstrează baza; doar codul circulă.
- Server nativ: `/opt/greentech-financiar`, serviciu `greentech-financiar`, conf `/etc/greentech-financiar/odoo.conf`, user `gt_financiar`, port `127.0.0.1:8070`.
- Deploy: backup `pg_dump` → `git pull` → `-i` module noi / `-u` module schimbate → restart → health check.
- Flux zilnic: commit pe `main` → `motor\PUBLICA.cmd` (push + ssh `deploy.sh`). Scripturi: `motor/deploy/server/{deploy,rollback,bootstrap-git}.sh`, `install-modules.txt`.

## Pași (status)

- [x] modul greentech_focus_financiar
- [x] modul greentech_theme
- [x] .gitignore + istorie curată (branch `main`, commit `c7959f6`)
- [x] scripturi deploy server + PUBLICA local
- [x] repo GitHub privat https://github.com/emxtufan/greentech-odoo (`main` urcat; deploy key: se adaugă la bootstrap)
- [ ] verificare cheie SSH server (host key schimbat!)
- [ ] bootstrap server (clone + addons_path)
- [ ] primul deploy

## Probleme deschise

- Host key SSH al serverului schimbat; utilizatorul spune că NU a reinstalat serverul → NU ne conectăm până verifică amprenta în consola furnizorului (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`; trebuie `SHA256:ulD51hFDRzdDjiuwop8cJcoqyDXF9vgKwxV1F6/NA/4`).
- Branch local `master` conține parole în istoric — NU se urcă; de șters după ce `main` e stabil.
- Varianta instalată pe server (nativ vs Docker) neconfirmată.
- `motor\03-PORNESTE-ODOO.cmd` s-a blocat la ultima repornire.
