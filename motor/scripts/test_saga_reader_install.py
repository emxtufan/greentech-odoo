"""Reader import regressions and installer orchestration; no Linux execution claimed."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import sys
import tempfile
import shutil
import hashlib
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
reader = runpy.run_path(str(ROOT/'custom_addons/greentech_saga_import/reader/extract_linux.py'))
checks = []
skipped = []
namespace = ModuleType('fdb')
namespace.__path__ = ['/venv/site-packages/fdb']
with patch.dict(sys.modules, {'fdb': namespace}):
    try:
        reader['load_driver']()
    except RuntimeError as error:
        assert 'utilizatorul serviciului' in str(error)
        assert '/venv/site-packages/fdb' in str(error)
    else:
        raise AssertionError('Namespace-only fdb accepted')
checks.append('namespace_only_fdb_fails_with_actionable_diagnostic')
valid = ModuleType('fdb')
valid.connect = lambda: None
with patch.dict(sys.modules, {'fdb': valid}):
    assert reader['load_driver']() is valid
checks.append('callable_driver_api_accepted')

source = (ROOT/'deploy/financiar/update_saga_template.py').read_text(encoding='utf-8')
tree = ast.parse(source)
definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'require', 'install_reader_driver'}]
calls = []
def fake_run(args, **kwargs):
    args = [str(a) for a in args]
    calls.append((args, kwargs))
    if args[0] == 'runuser':
        if failure[0]:
            raise RuntimeError('driver unreadable as service user')
        return '{"connect": true}'
    if 'uv' in args:
        return ''
    return '1.17.0\n'
failure = [False]
scope = dict(ROOT=Path('/opt/greentech-financiar'), DATA=Path('/var/lib/greentech-financiar'),
             PYTHON=Path('/opt/greentech-financiar/venv/bin/python'), os=os, re=re, run=fake_run)
exec(compile(ast.Module(body=definitions, type_ignores=[]), '<installer-functions>', 'exec'), scope)
with contextlib.redirect_stdout(io.StringIO()):
    scope['install_reader_driver']()
install = next((args, kw) for args, kw in calls if 'uv' in args)
assert install[1]['umask'] == 0o022
assert '--no-cache' in install[0] and install[0][install[0].index('--link-mode')+1] == 'copy'
assert 'six==1.17.0' in install[0] and 'fdb==2.0.4' in install[0]
assert install[0].count('--reinstall-package') == 2
probe, kwargs = calls[-1]
assert probe[:4] == ['runuser','-u','gt_financiar','--'] and '-I' in probe
assert kwargs['cwd'] == scope['DATA']
compile(probe[-1], '<driver-probe>', 'exec')
checks.append('reinstall_preserves_six_version_and_sets_service_readable_permissions')
checks.append('api_probe_runs_isolated_as_service_user')
failure[0] = True
try:
    with contextlib.redirect_stdout(io.StringIO()):
        scope['install_reader_driver']()
except RuntimeError as error:
    assert 'unreadable' in str(error)
else:
    raise AssertionError('Failed probe did not abort')
checks.append('unreadable_driver_aborts_installation')
assert not any('systemctl' in args for args, _ in calls)
runtime_functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'require','copy_runtime_file'}]
runtime_scope = dict(Path=Path, os=os, tempfile=tempfile, shutil=shutil, hashlib=hashlib)
exec(compile(ast.Module(body=runtime_functions, type_ignores=[]), '<runtime-functions>', 'exec'), runtime_scope)
with tempfile.TemporaryDirectory(prefix='saga-runtime-test-') as temp:
    root = Path(temp)
    runtime = root/'private'
    runtime.mkdir()
    source = root/'system-engine.so'
    source.write_bytes(b'synthetic ELF fixture, no executable code')
    original = source.read_bytes()
    destination = runtime/'plugins/libEngine12.so'
    runtime_scope['copy_runtime_file'](source, destination, runtime)
    assert not destination.is_symlink() and destination.read_bytes() == original
    assert source.read_bytes() == original
    runtime_scope['copy_runtime_file'](source, destination, runtime)
    assert destination.read_bytes() == original
    checks.append('private_engine_copy_is_regular_verified_and_idempotent')
    try:
        runtime_scope['copy_runtime_file'](source, root/'escape.so', runtime)
    except RuntimeError:
        assert not (root/'escape.so').exists()
    else:
        raise AssertionError('Runtime boundary accepted outside destination')
    checks.append('runtime_copy_refuses_outside_destination')
    link = runtime/'plugins/known-link.so'
    try:
        link.symlink_to(source)
    except OSError:
        skipped.append('symlink_replacement_not_executable_on_windows')
    else:
        runtime_scope['copy_runtime_file'](source, link, runtime)
        assert not link.is_symlink() and link.read_bytes() == original and source.read_bytes() == original
        checks.append('existing_symlink_replaced_without_changing_system_library')
    unknown = runtime/'plugins/unknown-link.so'
    if link.exists() and link.is_file() and 'existing_symlink_replaced_without_changing_system_library' in checks:
        other = root/'other.so'
        other.write_bytes(b'other')
        unknown.symlink_to(other)
        try:
            runtime_scope['copy_runtime_file'](source, unknown, runtime)
        except RuntimeError:
            assert unknown.is_symlink() and other.read_bytes() == b'other'
        else:
            raise AssertionError('Unknown symlink was overwritten')
        checks.append('unknown_symlink_is_preserved_and_rejected')
engine_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare_engine')
probe_node = next(n for n in engine_fn.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'probe')
compile(ast.literal_eval(probe_node.value), '<engine-symbol-probe>', 'exec')
report = {'passed':len(checks), 'checks':checks, 'skipped':skipped, 'linux_execution_verified':False}
(ROOT/'logs/saga-deploy/reader-install-tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
