"""Concurrent requests and official D300 validation in the isolated clone."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from financial_client import Client

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "logs/advances-20261020"
state = json.loads((WORK / "state.json").read_text())
browser = json.loads((WORK / "browser-test.json").read_text())
fixture = json.loads((WORK / "fixture.json").read_text())
c = Client()
c.base = "http://127.0.0.1:8072"
c.context["allowed_company_ids"] = [1]
c.uid = c.rpc("/web/session/authenticate", {
    "db": state["database"], "login": c.credentials["login"], "password": c.credentials["password"]})["uid"]
assert state["database"].startswith("gt_d112_")
case = browser["cases"]["sale"]
source = c.search("account.move.line", [
    ("move_id", "=", case["advance"]), ("display_type", "=", "product")],
    ["id", "tax_ids"])[0]
service = c.search("account.move.line", [
    ("move_id", "=", case["final"]), ("gt_advance_origin_id", "=", False),
    ("display_type", "=", "product")], ["account_id"])[0]
drafts, wizards = [], []
for n in range(2):
    move = c.call("account.move", "create", [[{
        "company_id": 1, "partner_id": fixture["partner"], "move_type": "out_invoice",
        "invoice_date": "2026-09-22", "date": "2026-09-22", "ref": "TEST CONCURENTA " + str(n),
        "invoice_line_ids": [[0, 0, {"name": "Test concurenta", "account_id": service["account_id"][0],
            "price_unit": 1000, "quantity": 1, "tax_ids": [[6, 0, source["tax_ids"]]]}]],
    }]])[0]
    drafts.append(move)
    wizards.append(c.call("gt.advance.allocate", "create", [[{
        "move_id": move, "source_id": source["id"], "amount": 400}]])[0])
barrier = threading.Barrier(2)


def consume(wizard):
    worker = Client.__new__(Client)
    worker.base = c.base
    worker.context = c.context.copy()
    worker.session = requests.Session()
    worker.session.cookies.update(c.session.cookies)
    barrier.wait(timeout=10)
    try:
        worker.call("gt.advance.allocate", "action_apply", [[wizard]])
        return {"accepted": True}
    except Exception as exc:
        return {"accepted": False, "reason": str(exc)}


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(consume, wizards))
assert sum(r["accepted"] for r in results) == 1, results
assert "disponibil" in next(r["reason"] for r in results if not r["accepted"]).lower(), results
c.call("gt.advance.allocate", "unlink", [wizards])
c.call("account.move", "unlink", [drafts])
assert c.read("account.move", case["advance"], ["gt_advance_remaining"])["gt_advance_remaining"] == 600

# Reuse company identity/settings, but calculate a separate period in the clone.
action = c.call("gt.anaf.d300", "action_revision", [[1]])
declaration = action["res_id"]
c.write("gt.anaf.d300", declaration, {"month": 9, "year": 2026, "period_type": "L",
    "vat_registered": True, "balances_reviewed": True, "special_reviewed": True})
c.call("gt.anaf.d300", "action_calculate", [[declaration]])
d = c.read("gt.anaf.d300", declaration, ["data", "state"])
assert not d["data"]["errors"], d["data"]["errors"]
rows = {r["code"]: r for r in d["data"]["rows"]}
existing = {}
for kind in ("sale", "purchase"):
    journal = c.call("gt.ro.vat.journal", "create", [[{
        "company_id": 1, "kind": kind, "date_from": "2026-09-01", "date_to": "2026-09-30"}]])[0]
    c.call("gt.ro.vat.journal", "action_refresh", [[journal]])
    report = c.read("gt.ro.vat.journal", journal, ["data"])["data"]
    existing[kind] = round(sum(r["eligible"] for r in report["rows"]
                               if r["partner"] != "DEMO AVANSURI - test izolat"))
assert (rows["19"]["tax"], rows["31"]["tax"]) == (651 + existing["sale"], 651 + existing["purchase"])
c.call("gt.anaf.d300", "action_validate", [[declaration]])
d = c.read("gt.anaf.d300", declaration, ["state", "duk_log"])
assert d["state"] == "valid" and d["duk_log"].strip() == "ok", d
result = {"concurrency": results, "d300": {"id": declaration, **d,
          "collected_vat": rows["19"]["tax"], "deductible_vat": rows["31"]["tax"],
          "existing_vat": existing, "advance_fixture_vat_each_side": 651}}
(WORK / "extra-verified.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
print("ADVANCES_CONCURRENCY_AND_OFFICIAL_D300_OK")
