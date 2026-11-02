"""Prepare/upgrade and seed ONLY the explicitly named fictitious company."""
import argparse
import json
import subprocess
import d112_native_deploy as deploy

b = deploy.base
b.WORK = b.ROOT / "logs/d112-demo-20261020"


def seed(target):
    config = b.LIVE if target == "live" else b.WORK / "test.conf"
    code = (b.ROOT / "scripts/d112_demo_seed_odoo.py").read_text(encoding="utf-8")
    code = "TARGET = " + repr(target) + "\n" + code
    r = subprocess.run([str(b.PYTHON), str(b.ODOO), "shell", "-c", str(config), "--no-http"],
                       input=code, text=True, encoding="utf-8", env=b.ENV, cwd=b.ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (b.WORK / (target + "-seed.log")).write_text(r.stdout, encoding="utf-8")
    if r.returncode or "D112_DEMO_SEEDED_OK" not in r.stdout:
        raise RuntimeError("Seed failed; inspect seed.log. Transaction was not committed.")
    b.check(target)
    print("D112_DEMO_SEEDED_OK", target)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "test", "live", "seed-test", "seed-live", "stop-test", "check-live"])
    action = p.parse_args().action
    if action == "prepare":
        b.prepare()
    elif action in ("test", "live"):
        deploy.install(action)
    elif action.startswith("seed-"):
        seed(action.removeprefix("seed-"))
    elif action == "stop-test":
        b.stop_test()
    else:
        b.check("live")
