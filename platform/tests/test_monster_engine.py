from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.monster_v3_fixtures import (
    STAR13_ACTIONS,
    write_effect_image_list,
    write_smartmonster_ini,
    write_wzl_wzx_pair,
)
from xydp.monster_engine import (
    build_smartmonster_closure,
    classify_engine_mode,
    derive_donor_server_root,
    parse_effect_image_list,
    rewrite_smartmonster_ini,
)


class MonsterEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="monster-engine-")
        self.root = Path(self.temporary.name)
        self.server = self.root / "donor-server"
        self.client_data = self.root / "client" / "data"
        self.smart_ini = self.server / "Mir200" / "Envir" / "SmartMonster" / "黄金夹具怪.ini"
        self.effect_list = self.server / "Mir200" / "Envir" / "EffectImageList.txt"
        self.client_data.mkdir(parents=True)
        write_wzl_wzx_pair(self.client_data, "Mon7")
        write_smartmonster_ini(self.smart_ini)
        write_effect_image_list(
            self.effect_list,
            [f"Existing{index}.wzl" for index in range(78)] + ["Mon7.wzl"],
        )
        self.monster = {"Name": "黄金夹具怪", "Race": 156, "RaceImg": 156, "Appr": 1123}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def closure(self, smart_ini: Path | None = None):
        return build_smartmonster_closure(
            self.monster,
            self.smart_ini if smart_ini is None else smart_ini,
            self.effect_list,
            [self.client_data],
            {},
        )

    def test_star13_equivalent_closure_collects_all_zero_based_dependencies(self) -> None:
        """若漏掉任一ActionFile或EffectFile，13处引用与224帧黄金闭包必须失败。"""
        closure = self.closure()
        self.assertEqual(closure.engine_mode, "smartmonster")
        self.assertEqual(closure.closure_status, "ready_verified")
        self.assertEqual(closure.total_verified_play_frames, 224)
        self.assertEqual(closure.resource_reference_counts, {"ActionFile": 12, "EffectFile": 1})
        self.assertEqual(len(closure.dependencies), 1)
        self.assertEqual(closure.dependencies[0].source_index, 78)
        self.assertEqual(closure.login_policy, "custom_monster_dat_required")
        self.assertEqual(closure.capability_policy, "basic_melee")

    def test_raceimg156_without_same_name_ini_is_incomplete(self) -> None:
        """若RaceImg=156缺同名INI却仍标记ready，会把不完整自定义怪物放进随机池。"""
        missing = self.smart_ini.with_name("不存在.ini")
        closure = self.closure(missing)
        self.assertEqual(classify_engine_mode(self.monster, missing), "smartmonster")
        self.assertEqual(closure.closure_status, "incomplete")
        self.assertIn("INI", closure.reason or "")

    def test_zero_based_78_resolves_physical_line_79(self) -> None:
        """若把编号78解释成第78物理行，会解析为Existing77而非Mon7。"""
        document = parse_effect_image_list(self.effect_list)
        self.assertEqual(document.lines[78], "Mon7.wzl")
        self.assertEqual(self.closure().dependencies[0].entry, "Mon7.wzl")

    def test_complex_server_attack_is_not_random_ready(self) -> None:
        """若额外ServerAttack仍为ready_verified，会无意迁入供体特殊能力。"""
        write_smartmonster_ini(self.smart_ini, extra_attack=True)
        closure = self.closure()
        self.assertEqual(closure.closure_status, "complex_ability")
        self.assertNotEqual(closure.closure_status, "ready_verified")
        self.assertIn("ServerAttack1", closure.reason or "")

    def test_enabled_server_attack_above_5_is_complex_ability(self) -> None:
        """若只检查1至5号攻击，已启用的ServerAttack6会错误进入随机闭包。"""
        self.smart_ini.write_bytes(
            self.smart_ini.read_bytes()
            + b"[ServerAttack6]\r\nAttackEnabled=1\r\nAttackMode=0\r\n"
        )
        closure = self.closure()
        self.assertEqual(closure.closure_status, "complex_ability")
        self.assertIn("ServerAttack6", closure.reason or "")

    def test_required_action_without_action_file_is_incomplete(self) -> None:
        """若ActStand缺少ActionFile仍被跳过，站立帧就未被真实验证却可随机使用。"""
        lines = self.smart_ini.read_text(encoding="gb18030").splitlines()
        section_start = lines.index("[ActStand]")
        action_line = lines.index("ActionFile=78", section_start)
        del lines[action_line]
        self.smart_ini.write_bytes(("\r\n".join(lines) + "\r\n").encode("gb18030"))
        closure = self.closure()
        self.assertEqual(closure.closure_status, "incomplete")
        self.assertIn("ActStand", closure.reason or "")
        self.assertIn("ActionFile", closure.reason or "")

    def test_closure_hash_is_stable_across_equivalent_donor_roots(self) -> None:
        """若哈希纳入供体绝对路径，相同闭包迁到另一目录会失去稳定身份。"""
        other_root = self.root / "same-content-other-root"
        other_ini = other_root / "server" / "Mir200" / "Envir" / "SmartMonster" / self.smart_ini.name
        other_effect = other_root / "server" / "Mir200" / "Envir" / "EffectImageList.txt"
        other_data = other_root / "client" / "data"
        other_ini.parent.mkdir(parents=True)
        other_data.mkdir(parents=True)
        other_ini.write_bytes(self.smart_ini.read_bytes())
        other_effect.write_bytes(self.effect_list.read_bytes())
        (other_data / "Mon7.wzl").write_bytes((self.client_data / "Mon7.wzl").read_bytes())
        (other_data / "Mon7.wzx").write_bytes((self.client_data / "Mon7.wzx").read_bytes())
        other_closure = build_smartmonster_closure(
            self.monster, other_ini, other_effect, [other_data], {}
        )
        self.assertEqual(self.closure().closure_hash, other_closure.closure_hash)

    def test_closure_hash_changes_when_effect_image_list_bytes_change(self) -> None:
        """若哈希遗漏EffectImageList证据，零基映射依据漂移不会使候选作废。"""
        before = self.closure().closure_hash
        self.effect_list.write_bytes(self.effect_list.read_bytes() + b"Unreferenced.wzl\r\n")
        after = self.closure().closure_hash
        self.assertNotEqual(before, after)

    def test_rewrite_changes_every_non_negative_resource_reference(self) -> None:
        """若只重写ActionFile或遗漏任意非负白名单资源，目标INI会继续指向供体索引。"""
        ini = (
            b"[A]\r\nActionFile=78\r\nEffectFile=12\r\nHPFile=-1\r\n"
            b"[B]\r\nTarget_File=78\r\nFly_File=12\r\n"
        )
        rewritten = rewrite_smartmonster_ini(ini, {78: 14, 12: 15}).decode("utf-8")
        self.assertIn("ActionFile=14", rewritten)
        self.assertIn("EffectFile=15", rewritten)
        self.assertIn("HPFile=-1", rewritten)
        self.assertIn("Target_File=14", rewritten)
        self.assertIn("Fly_File=15", rewritten)
        self.assertNotIn("=78", rewritten)
        self.assertNotIn("=12", rewritten)

    def test_effect_document_preserves_raw_text_contract_and_rejects_empty_reference(self) -> None:
        """若规范化BOM、换行或跳过空物理行，零基资源编号会漂移。"""
        raw_path = self.root / "raw-effect.txt"
        raw = b"\xef\xbb\xbfFirst.wzl\r\n\r\nThird.wzl\r\n"
        raw_path.write_bytes(raw)
        document = parse_effect_image_list(raw_path)
        self.assertEqual(document.raw, raw)
        self.assertEqual(document.bom, b"\xef\xbb\xbf")
        self.assertEqual(document.newline, "\r\n")
        self.assertEqual(document.lines, ("First.wzl", "", "Third.wzl"))
        empty_reference = self.root / "empty-reference.txt"
        write_effect_image_list(
            empty_reference, [f"Existing{index}.wzl" for index in range(78)] + [""],
        )
        closure = build_smartmonster_closure(
            self.monster, self.smart_ini, empty_reference, [self.client_data], {}
        )
        self.assertEqual(closure.closure_status, "incomplete")
        self.assertIn("空行", closure.reason or "")

    def test_derive_donor_server_root_requires_mud2_db_layout(self) -> None:
        """若数据库路径不是标准Mud2/DB层级却被接受，扫描会误读不相干服务端。"""
        database = self.server / "Mud2" / "DB" / "ApexM2.DB"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"")
        self.assertEqual(derive_donor_server_root(database), self.server)
        with self.assertRaisesRegex(RuntimeError, "Mud2"):
            derive_donor_server_root(self.root / "ApexM2.DB")

    def test_invalid_monster_frame_type_is_incomplete(self) -> None:
        """若非259/261帧也通过动作验证，错误资源会进入默认随机池。"""
        write_wzl_wzx_pair(self.client_data, "Mon7", STAR13_ACTIONS, frame_type=6)
        closure = self.closure()
        self.assertEqual(closure.closure_status, "incomplete")
        self.assertIn("帧类型", closure.reason or "")


if __name__ == "__main__":
    unittest.main()
