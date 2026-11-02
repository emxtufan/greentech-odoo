"""Read-only HTTP/RPC smoke check on the local financial instance."""
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse

from financial_client import Client

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "logs/oca-ro-install-20261020"
c = Client()
assert c.uid
result = {"url": c.base, "authenticated": True, "assets": [], "models": []}
page = c.session.get(c.base + "/odoo", timeout=45)
page.raise_for_status()
assert "web.assets_web" in page.text
for url in sorted(set(re.findall(r'(?:src|href)="([^"]*/web/assets/[^"]+)"', page.text))):
    full = urljoin(c.base, url)
    assert urlparse(full).netloc == urlparse(c.base).netloc
    response = c.session.get(full, timeout=120)
    response.raise_for_status()
    assert response.content and b"Could not get content for" not in response.content
    if urlparse(full).path.endswith(".css"):
        assert b"The style compilation failed" not in response.content
    result["assets"].append({"path": url, "bytes": len(response.content), "status": response.status_code})
assert result["assets"]
menus = c.session.get(c.base + "/web/webclient/load_menus?lang=ro_RO", timeout=30)
menus.raise_for_status()
menu_data = menus.json()
result["menus"] = len(menu_data)
menu_text = json.dumps(menu_data, ensure_ascii=False)
assert "SPV" in menu_text, "SPV menu not available to admin"
for model in ("account.move", "account.payment", "account.journal", "res.partner",
              "l10n.ro.message.spv", "account.statement.import", "stock.picking"):
    view = c.call(model, "get_views", [], {"views": [[False, "list"], [False, "form"]]})
    assert view.get("views")
    result["models"].append(model)
selected = json.loads((WORK / "selection.json").read_text())["modules"]
installed = c.search("ir.module.module", [("name", "in", selected)], ["name", "state", "latest_version"])
assert len(installed) == len(selected) and all(x["state"] == "installed" for x in installed)
result["selected_installed"] = len(installed)
result["companies"] = c.search("res.company", [], [
    "name", "l10n_ro_accounting", "l10n_ro_property_vat_on_payment_position_id",
    "l10n_ro_nondeductible_account_id",
])
result["companies_with_spv_token"] = c.call("res.company", "search_count", [
    [("l10n_ro_edi_access_token", "!=", False)]
])
result["status"] = "passed"
(WORK / "http-verified.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("OCA_HTTP_OK", result["selected_installed"], "selected modules", len(result["assets"]), "assets", result["menus"], "menus")
