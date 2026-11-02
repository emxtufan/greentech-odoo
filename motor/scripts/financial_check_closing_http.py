"""Check the installed wizard over HTTP without posting accounting entries."""
import json
from financial_client import Client

c = Client()
before = c.call('account.move', 'search_count', [[('l10n_ro_close_id','!=',False)]])
w = c.call('l10n.ro.account.period.closing.wizard','create',[[{
    'closing_id':2, 'journal_id':9, 'date_from':'2026-09-01', 'date_to':'2026-09-30'}]])[0]
try:
    c.call('l10n.ro.account.period.closing.wizard','do_close',[[w]])
except RuntimeError as error:
    assert 'Nu există solduri de închis' in str(error), str(error)
else:
    raise AssertionError('Empty closing unexpectedly accepted')
assert before == c.call('account.move','search_count',[[('l10n_ro_close_id','!=',False)]])
view = c.call('l10n.ro.account.period.closing.wizard','get_views',[],{'views':[[False,'form']]})
assert 'Generează nota de închidere' in json.dumps(view,ensure_ascii=False)
print('HTTP verified: clear empty-period error, no new closing entries, updated wizard form.')
