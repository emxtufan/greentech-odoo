"""Configure local Java and validate only the explicitly generated DEMO D112."""
import json
from pathlib import Path
from financial_client import Client

ROOT = Path(__file__).resolve().parents[1]
work = ROOT / "logs/d112-java-20261020"
installation = json.loads((work / "installation.json").read_text())
demo = json.loads((ROOT / "logs/d112-demo-20261020/live-demo.json").read_text(encoding="utf-8"))
client = Client()
company = client.read("res.company", demo["company_id"], ["name"])
assert company["name"] == "GreenTech Financiar DEMO - date fictive"
client.context["allowed_company_ids"] = [demo["company_id"]]
fields = ["state", "company_id", "payroll_period_id", "filing_index", "receipt",
          "duk_log", "schema_log", "validated_hash", "validator_manifest", "pdf_filename"]
before = client.read("gt.anaf.d112", demo["declaration_id"], fields)
assert before["company_id"][0] == demo["company_id"] and before["payroll_period_id"][0] == demo["period_id"]
assert not before["filing_index"] and not before["receipt"]
if not (work / "before-validation.json").exists():
    (work / "before-validation.json").write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
period = client.read("gt.ro.payroll.period", demo["period_id"], ["state", "line_ids", "net"])
if period["state"] == "draft":
    lines = client.call("gt.ro.payroll.line", "read", [period["line_ids"]],
                        {"fields": ["employee_id", "worked_days", "bonus"]})
    assert {line["employee_id"][0] for line in lines} == {2, 3, 4}
    assert all(line["worked_days"] == 22 and line["bonus"] == 0 for line in lines)
    client.call("gt.ro.payroll.line", "write", [period["line_ids"], {"confirmed": True}])
    client.call("gt.ro.payroll.period", "action_compute", [[demo["period_id"]]])
    period = client.read("gt.ro.payroll.period", demo["period_id"], ["state", "net"])
    assert period["state"] == "calculated" and period["net"] == 19315
if period["state"] == "calculated":
    action = client.call("gt.ro.payroll.period", "action_generate_d112", [[demo["period_id"]]])
    demo["declaration_id"] = action["res_id"]
    client.write("gt.anaf.d112", demo["declaration_id"], {"filing_note":
                 "DATE FICTIVE, EXCLUSIV TEST SOFTWARE. NU SE SEMNEAZĂ ȘI NU SE DEPUNE LA ANAF."})
    (ROOT / "logs/d112-demo-20261020/live-demo.json").write_text(
        json.dumps(demo, ensure_ascii=False, indent=2), encoding="utf-8")
client.call("ir.config_parameter", "set_param", ["gt_anaf.java_path", installation["java_path"]])
client.call("gt.anaf.d112", "action_validate_anaf", [[demo["declaration_id"]]])
result = client.read("gt.anaf.d112", demo["declaration_id"], fields)
(work / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
