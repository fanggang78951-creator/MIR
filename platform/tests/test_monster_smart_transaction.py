from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

from xydp.monster_engine import EngineDependency


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class SmartMonsterTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="smart-monster-transaction-")
        self.root = Path(self.temporary.name)
        self.donor = self.root / "donor"
        self.server = self.root / "target-server"
        self.client_data = self.root / "target-client" / "data"
        self.smart_dir = self.server / "Mir200" / "Envir" / "SmartMonster"
        self.effect_list = self.server / "Mir200" / "Envir" / "EffectImageList.txt"
        self.donor.mkdir()
        self.smart_dir.mkdir(parents=True)
        self.client_data.mkdir(parents=True)
        self.effect_list.write_bytes(b"History0.wzl\r\nHistory1.wzl\r\n")
        self.target_wzl_pair("History0")
        self.target_wzl_pair("History1")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def snapshot_inputs(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.root)): sha256_file(path)
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }

    def target_wzl_pair(self, stem: str, content: bytes = b"TARGET") -> None:
        (self.client_data / f"{stem}.wzl").write_bytes(content)
        (self.client_data / f"{stem}.wzx").write_bytes(content + b"-WZX")

    def dependency(
        self,
        index: int,
        entry: str,
        content: bytes,
        companion: bytes | None = b"WZX",
        source_dir: str = "",
        pak_password: str | None = None,
    ) -> EngineDependency:
        source = self.donor / source_dir / entry
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        companion_path: Path | None = None
        if companion is not None:
            companion_path = source.with_suffix(".wzx")
            companion_path.write_bytes(companion)
        return EngineDependency(
            source_index=index,
            entry=entry,
            kind="wzl_wzx" if companion_path else "pak",
            source_path=str(source),
            companion_path=str(companion_path) if companion_path else None,
            source_hash=sha256_file(source),
            companion_hash=sha256_file(companion_path) if companion_path else None,
            pak_password=pak_password,
        )

    def record(self, monster_id: int, name: str, indices: list[int]) -> SimpleNamespace:
        ini = self.donor / f"{name}.ini"
        lines = ["[ActStand]"]
        for ordinal, index in enumerate(indices):
            key = ("ActionFile", "EffectFile", "Target_File")[ordinal % 3]
            lines.append(f"{key}={index}")
        ini.write_bytes(("\r\n".join(lines) + "\r\n").encode("gb18030"))
        return SimpleNamespace(
            monster_id=monster_id,
            monster_name=name,
            smart_ini_path=str(ini),
            smart_ini_hash=sha256_file(ini),
            engine_mode="smartmonster",
            closure_status="ready_verified",
        )

    def build(self, records, dependencies):
        from xydp.monster_smart_transaction import build_smartmonster_batch

        return build_smartmonster_batch(records, dependencies, self.server, self.client_data)

    def test_batch_allocates_zero_based_indices_without_reordering_history(self):
        """若按一基或重排历史行，迁入后SmartMonster会解析到错误资源。"""
        dependency = self.dependency(78, "Body.wzl", b"BODY")
        record = self.record(101, "目标怪甲", [78])
        before = self.snapshot_inputs()

        plan = self.build([record], {101: [dependency]})

        self.assertEqual(plan.blockers, ())
        self.assertTrue(plan.effect_list_after.startswith(self.effect_list.read_bytes()))
        self.assertEqual(plan.resource_mappings[0]["source_index"], 78)
        self.assertEqual(plan.resource_mappings[0]["target_index"], 2)
        self.assertEqual(self.snapshot_inputs(), before)

        from xydp.monster_library import MonsterLibraryPlan, MonsterLibraryService

        library_plan = MonsterLibraryPlan(self.server, self.client_data, (), (), (), [], [], [], [])
        self.assertEqual(library_plan.generated_files_after, {})
        self.assertEqual(library_plan.engine_assignments, ())
        self.assertFalse(library_plan.requires_custom_monster_dat)
        self.assertFalse(library_plan.requires_login_regeneration)
        self.assertIn("engine_assignments", MonsterLibraryService.plan_summary(library_plan))

    def test_multiple_source_indices_are_all_rewritten(self):
        """若只改首个资源号，后续动作或特效仍会引用供体EffectImageList。"""
        first = self.dependency(78, "Body.wzl", b"BODY")
        second = self.dependency(12, "Effect.wzl", b"EFFECT")
        record = self.record(102, "目标怪乙", [78, 12, 78])
        before = self.snapshot_inputs()

        plan = self.build([record], {102: [first, second]})

        ini = next(item.content for item in plan.generated_files if item.target_path.endswith("目标怪乙.ini"))
        mapping = {item["source_index"]: item["target_index"] for item in plan.resource_mappings}
        text = ini.decode("gb18030")
        self.assertIn(f"ActionFile={mapping[78]}", text)
        self.assertIn(f"EffectFile={mapping[12]}", text)
        self.assertIn(f"Target_File={mapping[78]}", text)
        self.assertNotIn("ActionFile=78", text)
        self.assertNotIn("EffectFile=12", text)
        self.assertEqual(self.snapshot_inputs(), before)

    def test_same_hash_dependency_is_reused_safely(self):
        """若同批同哈希重复追加，目标零基号会漂移并制造重复资源。"""
        dependency = self.dependency(78, "Body.wzl", b"SHARED")
        first = self.record(103, "目标怪丙", [78])
        second = self.record(104, "目标怪丁", [78])
        before = self.snapshot_inputs()

        plan = self.build([second, first], {104: [dependency], 103: [dependency]})

        self.assertEqual(plan.blockers, ())
        self.assertEqual(len([item for item in plan.generated_files if item.target_path.endswith(".wzl")]), 1)
        self.assertEqual(len([item for item in plan.generated_files if item.target_path.endswith(".wzx")]), 1)
        self.assertEqual({item["target_index"] for item in plan.resource_mappings}, {2})
        self.assertEqual(self.snapshot_inputs(), before)

    def test_same_name_different_hash_gets_independent_xy_name(self):
        """若仅按供体文件名命名，同名异内容会覆盖另一个怪物的资源。"""
        first = self.dependency(78, "Shared.wzl", b"FIRST", source_dir="first")
        second = self.dependency(12, "Shared.wzl", b"SECOND", source_dir="second")
        record = self.record(105, "目标怪戊", [78, 12])
        before = self.snapshot_inputs()

        plan = self.build([record], {105: [first, second]})

        names = [Path(item.target_path).name for item in plan.generated_files if item.target_path.endswith(".wzl")]
        self.assertEqual(len(names), 2)
        self.assertNotEqual(names[0], names[1])
        self.assertTrue(all(name.startswith("XY_MonV3_105_") for name in names))
        self.assertEqual(self.snapshot_inputs(), before)

    def test_partial_existing_target_is_blocker(self):
        """若WZL/WZX仅存在一半仍继续候选，后续部署会生成不可加载闭包。"""
        dependency = self.dependency(78, "Body.wzl", b"BODY")
        record = self.record(106, "目标怪己", [78])
        from xydp.monster_smart_transaction import target_resource_entry

        (self.client_data / target_resource_entry(106, 0, dependency)).write_bytes(b"STALE-WZL")
        before = self.snapshot_inputs()

        plan = self.build([record], {106: [dependency]})

        self.assertTrue(plan.blockers)
        self.assertTrue(any("不完整" in item for item in plan.blockers))
        self.assertEqual(plan.generated_files, ())
        self.assertEqual(self.snapshot_inputs(), before)

    def test_effect_list_drift_invalidates_plan(self):
        """若预检后EffectImageList被改动仍可提交，所有零基映射可能整体错位。"""
        dependency = self.dependency(78, "Body.wzl", b"BODY")
        record = self.record(107, "目标怪庚", [78])
        before = self.snapshot_inputs()

        plan = self.build([record], {107: [dependency]})
        self.assertEqual(self.snapshot_inputs(), before)
        self.effect_list.write_bytes(b"DRIFT\r\n" + self.effect_list.read_bytes())

        with self.assertRaisesRegex(RuntimeError, "EffectImageList.*漂移"):
            plan.assert_effect_list_unchanged()

        self.effect_list.write_bytes(b"History0.wzl\r\nHistory1.wzl\r\n")
        self.assertEqual(self.snapshot_inputs(), before)

    def test_reversed_dependency_iterables_produce_equal_plan(self):
        """若无ordinal的依赖按Iterable位置编号，反转列表会改变候选资源名和零基号。"""
        first = self.dependency(12, "First.wzl", b"FIRST")
        second = self.dependency(78, "Second.wzl", b"SECOND")
        record = self.record(108, "目标怪辛", [12, 78])
        before = self.snapshot_inputs()

        forward = self.build([record], {108: [first, second]})
        reversed_plan = self.build([record], {108: [second, first]})

        self.assertEqual(forward, reversed_plan)
        self.assertEqual(self.snapshot_inputs(), before)

    def test_cross_index_rewrite_validates_resource_keys_not_raw_bytes(self):
        """source 12→target 2、source 2→target 3时，合法的=2不能被当成供体残留。"""
        first = self.dependency(12, "First.wzl", b"FIRST")
        second = self.dependency(2, "Second.wzl", b"SECOND")
        record = self.record(109, "目标怪壬", [12, 2])
        self.effect_list.write_bytes(b"History0.wzl\r\n")
        before = self.snapshot_inputs()

        plan = self.build([record], {109: [first, second]})

        self.assertEqual(plan.blockers, ())
        mapping = {item["source_index"]: item["target_index"] for item in plan.resource_mappings}
        self.assertEqual(mapping, {2: 1, 12: 2})
        ini = next(item.content for item in plan.generated_files if item.target_path.endswith("目标怪壬.ini"))
        self.assertIn(b"ActionFile=2", ini)
        self.assertIn(b"EffectFile=1", ini)
        self.assertEqual(self.snapshot_inputs(), before)

    def test_pak_metadata_preserves_password_and_reuse_is_password_scoped(self):
        """PAK候选必须保留密码，并只在hash和密码均相同的情况下复用。"""
        shared = self.dependency(78, "Shared.pak", b"PAK", None, "shared", "rule-one")
        other_password = self.dependency(12, "Shared.pak", b"PAK", None, "other", "rule-two")
        first = self.record(110, "目标怪癸", [78])
        second = self.record(111, "目标怪子", [78])
        before = self.snapshot_inputs()

        reused = self.build([first, second], {110: [shared], 111: [shared]})

        self.assertEqual(reused.blockers, ())
        generated_paks = [item for item in reused.generated_files if item.target_path.endswith(".pak")]
        self.assertEqual(len(generated_paks), 1)
        self.assertEqual(getattr(generated_paks[0], "kind", None), "pak")
        self.assertEqual(getattr(generated_paks[0], "pak_password", None), "rule-one")
        self.assertEqual({item["pak_password"] for item in reused.resource_mappings}, {"rule-one"})
        self.assertEqual({item["kind"] for item in reused.resource_mappings}, {"pak"})

        separated = self.build([first], {110: [shared, other_password]})
        self.assertEqual(separated.blockers, ())
        self.assertEqual(len([item for item in separated.generated_files if item.target_path.endswith(".pak")]), 2)
        self.assertEqual(
            {item["pak_password"] for item in separated.resource_mappings}, {"rule-one", "rule-two"}
        )
        self.assertEqual(self.snapshot_inputs(), before)

    def test_registered_legacy_partial_pair_is_global_blocker(self):
        """非本批Legacy.wzl只有半套时也必须阻断，不能被匹配扫描静默跳过。"""
        self.effect_list.write_bytes(b"Legacy.wzl\r\nHistory0.wzl\r\nHistory1.wzl\r\n")
        (self.client_data / "Legacy.wzl").write_bytes(b"LEGACY")
        dependency = self.dependency(78, "Body.wzl", b"BODY")
        record = self.record(112, "目标怪丑", [78])
        before = self.snapshot_inputs()

        plan = self.build([record], {112: [dependency]})

        self.assertTrue(plan.blockers)
        self.assertTrue(any("Legacy.wzl" in item and "不完整" in item for item in plan.blockers))
        self.assertEqual(plan.generated_files, ())
        self.assertEqual(self.snapshot_inputs(), before)

    def test_effect_list_exact_bytes_and_generated_hashes(self):
        """BOM、空物理行、混合换行与无末尾换行必须保留前缀且候选哈希精确。"""
        raw = b"\xef\xbb\xbfFirst.wzl\r\n\r\nLast.wzl\rTail.wzl"
        self.effect_list.write_bytes(raw)
        self.target_wzl_pair("First")
        self.target_wzl_pair("Last")
        self.target_wzl_pair("Tail")
        dependency = self.dependency(78, "Body.wzl", b"BODY")
        record = self.record(113, "目标怪寅", [78])
        before = self.snapshot_inputs()

        plan = self.build([record], {113: [dependency]})

        self.assertEqual(plan.blockers, ())
        self.assertTrue(plan.effect_list_after.startswith(raw))
        self.assertEqual(plan.resource_mappings[0]["target_index"], 4)
        self.assertTrue(plan.effect_list_after[len(raw):].startswith(b"\r\nXY_MonV3_113_0_"))
        self.assertTrue(all(item.after_hash == hashlib.sha256(item.content).hexdigest().upper() for item in plan.generated_files))
        self.assertEqual(self.snapshot_inputs(), before)

    def test_wzl_companion_hash_metadata_is_real_and_frozen(self):
        """WZL/WZX候选必须携带真实WZX哈希，且文件级元数据不能在事务前被改写。"""
        dependency = self.dependency(78, "Body.wzl", b"BODY", b"REAL-WZX")
        record = self.record(114, "目标怪卯", [78])
        before = self.snapshot_inputs()

        plan = self.build([record], {114: [dependency]})

        expected = sha256_file(Path(dependency.companion_path or ""))
        resources = [
            item for item in plan.generated_files
            if item.target_path.endswith(".wzl") or item.target_path.endswith(".wzx")
        ]
        self.assertEqual(plan.blockers, ())
        self.assertEqual(len(resources), 2)
        self.assertEqual({item.companion_hash for item in resources}, {expected})
        self.assertEqual({item["companion_hash"] for item in plan.resource_mappings}, {expected})
        with self.assertRaises(FrozenInstanceError):
            resources[0].companion_hash = "MUTATED"
        self.assertEqual(self.snapshot_inputs(), before)


if __name__ == "__main__":
    unittest.main()
