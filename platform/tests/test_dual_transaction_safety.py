import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xydp.mingge_dual import DualInstallPlan, _DualService, _change, _sha256


class Service(_DualService):
    route = 'safety-test'
    package_id = 'xy.test.safety'


def setup(base):
    server = base / 'server'; server.mkdir()
    source = base / 'source.txt'; source.write_bytes(b'input')
    for i in range(2): (server / f'{i}.txt').write_bytes(f'before-{i}'.encode())
    changes = tuple(_change(server, Path(f'{i}.txt'), 'exclusive', f'before-{i}'.encode(), f'after-{i}'.encode()) for i in range(2))
    plan = DualInstallPlan(Service.route, Service.package_id, 'test', server, source, _sha256(source.read_bytes()), changes, (), ())
    return Service(base / 'platform'), server, plan


class DualTransactionSafetyTests(unittest.TestCase):
    def test_an_actual_other_process_blocks_install_and_rollback_on_same_target(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            receipt = service.install(plan)
            code = "from pathlib import Path; import sys; from xydp.target_lock import target_lock\nwith target_lock(Path(sys.argv[1])):\n print('LOCKED', flush=True)\n sys.stdin.readline()\n"
            proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', code, str(server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                self.assertEqual(proc.stdout.readline().strip(), 'LOCKED')
                with self.assertRaisesRegex(Exception, '其他安装或回滚'): service.rollback(server, receipt.transaction_id)
                with self.assertRaisesRegex(Exception, '其他安装或回滚'): service.install(plan)
                from xydp.installer import Installer, InstallPlan
                from xydp.repository import PackageRepository
                installer = Installer(PackageRepository(Path(td) / 'packages'), Path(td) / 'backups')
                generic = InstallPlan(str(server), None, [], {}, {}, [])
                with self.assertRaisesRegex(Exception, '其他安装或回滚'): installer.install(generic)
                with self.assertRaisesRegex(Exception, '其他安装或回滚'): installer.rollback(server, 'not-used')
                self.assertEqual((server / '1.txt').read_bytes(), b'after-1')
            finally:
                proc.communicate('\n', timeout=15)
            service.rollback(server, receipt.transaction_id)
            self.assertEqual((server / '0.txt').read_bytes(), b'before-0')

    def test_distinct_targets_can_hold_independent_locks_and_recursion_is_rejected(self):
        from xydp.target_lock import target_lock
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / 'one'; second = Path(td) / 'two'
            first.mkdir(); second.mkdir()
            with target_lock(first), target_lock(second):
                with self.assertRaisesRegex(Exception, '其他安装或回滚'):
                    with target_lock(first): pass

    def test_rollback_io_failure_restores_only_its_committed_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            receipt = service.install(plan)
            replace = os.replace
            def fail_later(src, dest):
                if Path(dest) == server / '0.txt': raise OSError('rollback write failure')
                return replace(src, dest)
            with patch('xydp.mingge_dual.os.replace', side_effect=fail_later):
                with self.assertRaises(OSError): service.rollback(server, receipt.transaction_id)
            self.assertEqual((server / '0.txt').read_bytes(), b'after-0')
            self.assertEqual((server / '1.txt').read_bytes(), b'after-1')

    def test_final_atomic_check_detects_edit_during_temp_write(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            real_fsync = os.fsync
            once = False
            def mutate_during_fsync(fd):
                nonlocal once
                if not once:
                    once = True
                    (server / '0.txt').write_bytes(b'late-edit')
                return real_fsync(fd)
            with patch('xydp.mingge_dual.os.fsync', side_effect=mutate_during_fsync):
                with self.assertRaisesRegex(Exception, '变化'): service.install(plan)
            self.assertEqual((server / '0.txt').read_bytes(), b'late-edit')
            self.assertEqual((server / '1.txt').read_bytes(), b'before-1')

    def test_late_writer_to_second_target_is_preserved_and_first_is_recovered(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            replace = os.replace
            def racing_replace(src, dest):
                result = replace(src, dest)
                if Path(dest) == server / '0.txt':
                    (server / '1.txt').write_bytes(b'other-writer')
                return result
            with patch('xydp.mingge_dual.os.replace', side_effect=racing_replace):
                with self.assertRaisesRegex(Exception, '变化'): service.install(plan)
            self.assertEqual((server / '1.txt').read_bytes(), b'other-writer')
            self.assertEqual((server / '0.txt').read_bytes(), b'before-0')

    def test_first_replace_failure_never_restores_uncommitted_other_writer(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            def fail(src, dest):
                (server / '1.txt').write_bytes(b'other-writer')
                raise OSError('injected first replace failure')
            with patch('xydp.mingge_dual.os.replace', side_effect=fail):
                with self.assertRaises(OSError): service.install(plan)
            self.assertEqual((server / '1.txt').read_bytes(), b'other-writer')
            self.assertEqual((server / '0.txt').read_bytes(), b'before-0')

    def test_rollback_late_conflict_has_zero_writes(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            receipt = service.install(plan)
            (server / '0.txt').write_bytes(b'user-edit')
            with self.assertRaisesRegex(Exception, '变化'): service.rollback(server, receipt.transaction_id)
            self.assertEqual((server / '1.txt').read_bytes(), b'after-1')
            self.assertEqual((server / '0.txt').read_bytes(), b'user-edit')

    def test_failure_preserves_newer_edit_to_an_already_committed_target(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            replace = os.replace
            def fail_later(src, dest):
                if Path(dest) == server / '1.txt':
                    (server / '0.txt').write_bytes(b'newer-edit')
                    raise OSError('second write failed')
                return replace(src, dest)
            with patch('xydp.mingge_dual.os.replace', side_effect=fail_later):
                with self.assertRaises(Exception): service.install(plan)
            self.assertEqual((server / '0.txt').read_bytes(), b'newer-edit')

    def test_rollback_backup_corruption_has_zero_writes(self):
        with tempfile.TemporaryDirectory() as td:
            service, server, plan = setup(Path(td))
            receipt = service.install(plan)
            (receipt.receipt_path.parent / 'files/000.bin').write_bytes(b'corrupt')
            with self.assertRaisesRegex(Exception, '备份'): service.rollback(server, receipt.transaction_id)
            self.assertEqual((server / '1.txt').read_bytes(), b'after-1')
