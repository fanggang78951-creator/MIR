"""Build a matched GUI/CLI pair, verify executable code, then publish one receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()


def verified_test_commands(receipt_path, root, bound):
    receipt = json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    if receipt.get('source_and_package_fingerprints') != bound:
        raise RuntimeError('Verified test receipt does not match current source/package snapshot')
    tests = {p.relative_to(root).as_posix(): sha(p) for folder in ('tests','做装备/tests')
             for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if receipt.get('test_fingerprints') != tests:
        raise RuntimeError('Verified test receipt does not match current test files')
    checks = receipt.get('checks', [])
    if {c.get('label') for c in checks} != {'platform-tests','equipment-tests'} or len(checks) != 2:
        raise RuntimeError('Both complete test suites are required')
    for check in checks:
        log = Path(check['log'])
        if check.get('exit_code') != 0 or sha(log) != check.get('sha256'):
            raise RuntimeError('Test evidence is missing or changed')
        content = log.read_text(encoding='utf-8-sig')
        if not re.search(r'^Ran \d+ tests? in ', content, re.M) or not re.search(r'^OK(?: \(skipped=\d+\))?\s*$', content, re.M) or re.search(r'^FAILED', content, re.M):
            raise RuntimeError('Test evidence is not a successful complete suite')
    return [{**c, 'reused':True, 'verification_receipt':str(receipt_path)} for c in checks]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--release-id', required=True)
    p.add_argument('--publish', action='store_true')
    p.add_argument('--verified-tests', type=Path, help='Reuse complete test logs only when all source, package and test fingerprints match')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.release_id): raise ValueError('Invalid release identifier')
    root = a.root.resolve(); out = root / 'evidence' / a.release_id
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root/'src'))
    from xydp.release_identity import source_identity, code_fingerprint
    from PyInstaller.archive.readers import CArchiveReader
    expected = source_identity(root/'src')
    bound_paths = [p for folder in ('src/xydp', '做装备/src/xyequip', 'packages')
                   for p in (root/folder).rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts]
    bound_paths += [root/'run_gui.py', root/'run_cli.py', root/'build.ps1', root/'tools/build_platform_release.py',
                    root/'所需材料表格汇总/00_填写文档注册表.json',
                    root/'Start_XuanYuanDevPlatform.bat', root/'tools/Start-VerifiedPlatform.ps1']
    bound = {p.relative_to(root).as_posix(): sha(p) for p in bound_paths}
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(root/x) for x in ['src','做装备/src','vendor']),
               PYTHONIOENCODING='utf-8')
    build = root/'runtime'/('build-'+a.release_id); build.mkdir(parents=True, exist_ok=True)
    env['TEMP'] = str(build); env['TMP'] = str(build); env['PYINSTALLER_CONFIG_DIR'] = str(build/'config')
    commands = []
    def run(args, label):
        logfile = out/(label+'.log')
        with logfile.open('w', encoding='utf-8') as f:
            proc = subprocess.run(args, cwd=root, env=env, stdout=f, stderr=subprocess.STDOUT,
                                  timeout=180 if label == 'frozen-gui-smoke' else 3600)
        commands.append({'argv':[str(x) for x in args], 'exit_code':proc.returncode, 'log':str(logfile), 'sha256':sha(logfile)})
        (out/'commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2),encoding='utf-8')
        if proc.returncode:
            print(logfile.read_text(encoding='utf-8')[-6000:]); raise RuntimeError(f'{label} failed; see {logfile}')
        print(f'{label}: passed', flush=True)
        return logfile
    if a.verified_tests:
        commands.extend(verified_test_commands(a.verified_tests, root, bound))
        print('platform-tests and equipment-tests: verified existing complete logs; identical source/package/test snapshot',flush=True)
    else:
        run([sys.executable,'-m','unittest','discover','-s','tests','-v'],'platform-tests')
        run([sys.executable,'-m','unittest','discover','-s',str(root/'做装备/tests'),'-p','test_*.py','-v'],'equipment-tests')
    artifacts = {}
    for kind, script, name, mode in [('gui','run_gui.py','XuanYuanDevPlatform','--windowed'),('cli','run_cli.py','xydp-cli','--console')]:
        stem = name+'-'+a.release_id
        argv = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile',mode,'--name',stem,
                '--paths',str(root/'src'),'--paths',str(root/'做装备/src'),'--paths',str(root/'vendor'),
                '--collect-all','openpyxl','--collect-all','PIL','--collect-submodules','xydp',
                '--collect-submodules','xyequip.equipment_graphics',
                '--collect-data','xyequip.equipment_graphics',
                '--add-data',str(root/'做装备/profiles')+';做装备/profiles',
                '--add-data',str(root/'做装备/assets')+';做装备/assets',
                '--distpath',str(root/'bin'),'--workpath',str(build/kind),'--specpath',str(build/'spec')]
        for source in sorted((root/'src/xydp').glob('*.py')):
            argv += ['--add-data',str(source)+';xydp']
        argv.append(str(root/script))
        run(argv,kind+'-build')
        artifact = root/'bin'/(stem+'.exe')
        archive = CArchiveReader(str(artifact))
        pyz_names = [key for key in archive.toc if key.endswith('.pyz')]
        if len(pyz_names) != 1: raise RuntimeError('Ambiguous executable module archive')
        pyz = archive.open_embedded_archive(pyz_names[0])
        actual = {name: code_fingerprint(pyz.extract(name)) for name in expected}
        if actual != expected: raise RuntimeError(f'{kind} executable code does not match tested sources')
        (out/(kind+'-code-identity.json')).write_text(json.dumps(actual,sort_keys=True,indent=2),encoding='utf-8')
        artifacts[kind] = {'path':str(artifact.relative_to(root)).replace('\\','/'),'sha256':sha(artifact)}
        run([sys.executable,str(root/'tools/verify_frozen_provenance.py'),'--artifact',str(artifact),
             '--source-root',str(root/'src')],kind+'-raw-source-provenance')
    if source_identity(root/'src') != expected: raise RuntimeError('Source changed during build; release not published')
    if any(sha(root/p) != value for p, value in bound.items()):
        raise RuntimeError('Source, entry point or package changed during build; release not published')
    cli = root/artifacts['cli']['path']
    argv = [str(cli),'--root',str(root),'project-build-info']
    for name in expected: argv += ['--module',name]
    log = run(argv,'frozen-runtime-identity')
    if json.loads(log.read_text(encoding='utf-8')) != expected: raise RuntimeError('Loaded CLI code differs from sources')
    run([str(cli),'--root',str(root),'project-list','--query','洗练'],'frozen-project-overview')
    gui_report = out/'frozen-gui-smoke.json'
    run([str(root/artifacts['gui']['path']),'--overview-smoke-report',str(gui_report)],'frozen-gui-smoke')
    gui_result = json.loads(gui_report.read_text(encoding='utf-8'))
    if gui_result.get('status') != 'passed' or not gui_result.get('cards'):
        raise RuntimeError('Frozen GUI project overview smoke test failed')
    receipt = {'schema_version':1,'release_id':a.release_id,'created_at':datetime.now().isoformat(),
               **artifacts,'execution_fingerprints':expected,'source_and_package_fingerprints':bound,'commands':commands,
               'game_status':'待验证','target_written':False}
    (out/'release.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    if a.publish:
        dest = root/'catalog/current-release.json'
        temp = dest.with_suffix('.json.pending')
        temp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,dest)
    print(json.dumps({'release':str(out/'release.json'),'published':a.publish},ensure_ascii=False),flush=True)


if __name__ == '__main__': main()
