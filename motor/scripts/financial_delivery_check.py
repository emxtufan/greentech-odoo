"""Validate guide destinations, workbook figures and launcher syntax independently."""
import json
from pathlib import Path
from zipfile import ZipFile
from lxml import etree, html
from financial_client import Client, ROOT

c = Client()
guide = ROOT / 'GHID-FINANCIAR-DEMO.html'
doc = html.fromstring(guide.read_bytes())
assert len(doc.xpath('//section')) == 8
ids = doc.xpath('//@id')
assert len(ids) == len(set(ids))
assert c.credentials['password'] not in guide.read_text(encoding='utf-8')
links = set(doc.xpath('//a/@href'))
for url in links:
    if url.startswith(c.base):
        response = c.session.get(url, timeout=30)
        assert response.status_code == 200, url
    elif not url.startswith(('http:', 'https:')):
        assert (ROOT / url).is_file(), url
namespace = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
for name, value in {'pnl_report': 5200, 'balance_report': 121928, 'budget_report': 24200, 'mijloace_fixe': 11500}.items():
    with ZipFile(ROOT / ('logs/financial-exports/' + name + '.xlsx')) as z:
        numbers = []
        for path in z.namelist():
            if path.startswith('xl/worksheets/sheet') and path.endswith('.xml'):
                sheet = etree.fromstring(z.read(path))
                numbers.extend(float(v) for v in sheet.xpath("//x:c[not(@t) or @t='n']/x:v/text()", namespaces=namespace))
        assert value in numbers, (name, value)
        print('Native XLSX:', name, value)
assert not c.search('ir.ui.menu', [('name', 'ilike', '??')], ['name'])
verification = json.loads((ROOT / 'logs/financial-verification.json').read_text(encoding='utf-8'))
closing = json.loads((ROOT / 'logs/financial-closing-test.json').read_text())
assert closing['native_closing_test'] == 'passed' and closing['persisted'] is False
result = {'guide_sections': 8, 'checked_links': len(links), 'no_credentials_in_guide': True,
          'native_workbook_values_checked': 4, 'native_accounting_checks': len(verification['checks']),
          'closing_test_rolled_back': True}
(ROOT / 'logs/financial-delivery-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('Delivery checks passed:', result)
