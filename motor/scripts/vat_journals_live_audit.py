"""Read-only accounting coverage check; creates only disposable report snapshots."""
import json
from pathlib import Path
from financial_client import Client

c = Client()
result = {}
for company in c.search("res.company", [], ["id"]):
    cid = company["id"]
    dates = c.call("account.move", "search_read", [[("company_id", "=", cid), ("state", "=", "posted")]],
                   {"fields": ["date"], "order": "date asc", "limit": 1})
    if not dates:
        continue
    result[str(cid)] = {}
    for kind in ("purchase", "sale"):
        [rid] = c.call("gt.ro.vat.journal", "create", [[{
            "company_id": cid, "kind": kind, "date_from": dates[0]["date"], "date_to": "2026-10-31"}]],
            context={"allowed_company_ids": [cid]})
        c.call("gt.ro.vat.journal", "action_refresh", [[rid]], context={"allowed_company_ids": [cid]})
        [r] = c.call("gt.ro.vat.journal", "read", [[rid]], {"fields": ["data"]}, context={"allowed_company_ids": [cid]})
        result[str(cid)][kind] = {"report_id": rid, "rows": len(r["data"]["rows"]),
                                 "source_documents": len({line["move_id"] for line in r["data"]["rows"]}),
                                 "warnings": len(r["data"]["warnings"])}
Path("logs/vat-journals-20261020/live-coverage.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
