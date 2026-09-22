import tempfile
import sys
import unittest
from pathlib import Path

import xydp.textpatch as textpatch
from xydp.encoding import read_text_document, write_text_document
from xydp.target import TargetError, TargetInspector, is_executable_running
from xydp.textpatch import (
    TextPatchError,
    add_unique_line,
    ensure_mapinfo_flag,
    set_mapinfo_display_name,
    install_event_hook,
    install_managed_anchor_hook,
    install_managed_block,
    remove_event_hook,
    scan_labels,
    set_exclusive_unique_line,
)


class TargetAndTextTests(unittest.TestCase):
    def test_detects_lfm2_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "Mir200" / "Envir").mkdir(parents=True)
            (root / "Mir200" / "M2Server.exe").write_bytes(b"M2")
            (root / "Mir200" / "Envir" / "MapInfo.txt").write_text("[0 盟重]", encoding="utf-8")
            target = TargetInspector.inspect(root)
            self.assertEqual(target.engine, "LFM2")
            self.assertEqual(target.envir, root / "Mir200" / "Envir")

    def test_rejects_non_lfm2_target(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(TargetError):
                TargetInspector.inspect(Path(td))

    def test_running_process_is_detected_by_exact_executable_path(self):
        self.assertTrue(is_executable_running(Path(sys.executable)))

    def test_gb18030_round_trip_preserves_crlf(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "QFunction-0.txt"
            original = "[@Main]\r\n#SAY\r\n玄渊测试\r\n".encode("gb18030")
            path.write_bytes(original)
            doc = read_text_document(path)
            write_text_document(path, doc)
            self.assertEqual(path.read_bytes(), original)

    def test_duplicate_labels_are_reported_case_insensitively(self):
        labels = scan_labels("[@TakeOnEx]\n#ACT\nBREAK\n[@takeonex]\n#ACT\nBREAK\n")
        self.assertEqual(labels.duplicates, {"takeonex": [1, 4]})

    def test_managed_block_is_idempotent_and_detects_manual_edits(self):
        text = "[@Main]\r\n#ACT\r\nBREAK\r\n"
        first = install_managed_block(text, "xy.demo", "#IF\r\n#ACT\r\nSENDMSG 6 OK", "\r\n")
        second = install_managed_block(first.text, "xy.demo", "#IF\r\n#ACT\r\nSENDMSG 6 OK", "\r\n")
        self.assertEqual(first.text, second.text)
        edited = first.text.replace("SENDMSG 6 OK", "SENDMSG 6 CHANGED")
        with self.assertRaisesRegex(TextPatchError, "被手工修改"):
            install_managed_block(edited, "xy.demo", "#IF\r\n#ACT\r\nSENDMSG 6 OK", "\r\n", first.content_hash)

    def test_managed_block_can_adopt_one_exact_audited_legacy_hash(self):
        first = install_managed_block("", "xy.demo", "#IF\r\n#ACT\r\nSENDMSG 6 OLD", "\r\n")
        edited = first.text.replace("SENDMSG 6 OLD", "SENDMSG 6 LEGACY")
        begin = edited.index("\r\n") + 2
        end = edited.index("\r\n; XYDP-END")
        legacy_body = edited[begin:end]
        from xydp.textpatch import _managed_hash
        legacy_hash = _managed_hash(legacy_body)

        adopted = install_managed_block(
            edited,
            "xy.demo",
            "#IF\r\n#ACT\r\nSENDMSG 6 NEW",
            "\r\n",
            accepted_current_hashes=(legacy_hash,),
        )
        self.assertIn("SENDMSG 6 NEW", adopted.text)
        self.assertNotIn("SENDMSG 6 LEGACY", adopted.text)

        with self.assertRaises(TextPatchError):
            install_managed_block(
                edited,
                "xy.demo",
                "#IF\r\n#ACT\r\nSENDMSG 6 NEW",
                "\r\n",
                accepted_current_hashes=("0" * 64,),
            )

    def test_managed_block_can_take_over_one_unchanged_legacy_package_id(self):
        legacy = install_managed_block(
            "", "xy.optional.rage.command", "[@XY_RAGE_COMMAND]\r\n#ACT\r\nBREAK", "\r\n"
        )
        adopted = install_managed_block(
            legacy.text,
            "xy.optional.rage.core",
            "[@XY_RAGE_COMMAND]\r\n#ACT\r\nBREAK",
            "\r\n",
            legacy_package_ids=("xy.optional.rage.command",),
        )
        self.assertIn("XYDP-BEGIN xy.optional.rage.core", adopted.text)
        self.assertNotIn("XYDP-BEGIN xy.optional.rage.command", adopted.text)
        self.assertEqual(adopted.text.count("[@XY_RAGE_COMMAND]"), 1)

        with self.assertRaisesRegex(TextPatchError, "新旧受管块同时存在"):
            install_managed_block(
                adopted.text + "\r\n" + legacy.text,
                "xy.optional.rage.core",
                "[@XY_RAGE_COMMAND]\r\n#ACT\r\nBREAK",
                "\r\n",
                legacy_package_ids=("xy.optional.rage.command",),
            )

    def test_managed_block_preserves_mutable_extension_zone(self):
        content = (
            "[@XY_Recalc]\r\n#ACT\r\n"
            "; XYDP-EXTENSION-BEGIN EQUIP_POWER\r\n"
            "; XY_EQUIP_MAKER_POWER_ANCHOR\r\n"
            "; XYDP-EXTENSION-END EQUIP_POWER\r\nBREAK"
        )
        first = install_managed_block("", "xy.power", content, "\r\n")
        extended = first.text.replace(
            "; XY_EQUIP_MAKER_POWER_ANCHOR\r\n",
            "; XY_EQUIP_MAKER_POWER_ANCHOR\r\n#IF\r\nCHECKITEMW 新装备 1\r\n#ACT\r\nINC N$倍攻 20\r\n",
        )
        second = install_managed_block(extended, "xy.power", content, "\r\n")
        self.assertIn("CHECKITEMW 新装备 1", second.text)
        self.assertFalse(second.changed)

    def test_event_hook_preserves_mutable_extension_zone(self):
        hook = "; XYDP-EXTENSION-BEGIN EQUIP_ATTACK\n; XY_EQUIP_MAKER_ATTACK_ANCHOR\n; XYDP-EXTENSION-END EQUIP_ATTACK"
        first = install_event_hook("[@AttackDamage]\n#ACT\nBREAK\n", "xy.pve", "AttackDamage", hook, "\n")
        extended = first.text.replace("; XY_EQUIP_MAKER_ATTACK_ANCHOR\n", "; XY_EQUIP_MAKER_ATTACK_ANCHOR\nINC N$XY_PVE_Extra 20\n")
        second = install_event_hook(extended, "xy.pve", "AttackDamage", hook, "\n")
        self.assertIn("INC N$XY_PVE_Extra 20", second.text)

    def test_event_and_anchor_hooks_can_adopt_one_unchanged_legacy_owner(self):
        legacy_event = install_event_hook(
            "[@PlayDie]\n#IF\n#ACT\nBREAK\n",
            "xy.ops.rage-title",
            "PlayDie",
            "#IF\nCHECKFENGHAO 狂暴之力\n#ACT\nRECYCFENGHAO 狂暴之力",
            "\n",
        )
        adopted_event = install_event_hook(
            legacy_event.text,
            "xy.optional.rage.core",
            "PlayDie",
            "#IF\nCHECKFENGHAO 狂暴之力\n#ACT\nRECYCFENGHAO 狂暴之力",
            "\n",
            legacy_package_ids=("xy.ops.rage-title",),
        )
        self.assertIn("XYDP-HOOK-BEGIN xy.optional.rage.core PlayDie", adopted_event.text)
        self.assertNotIn("XYDP-HOOK-BEGIN xy.ops.rage-title PlayDie", adopted_event.text)

        legacy_anchor = install_managed_anchor_hook(
            "; XY_EQUIP_MAKER_DROP_ANCHOR\n",
            "xy.ops.rage-title",
            "XY_EQUIP_MAKER_DROP_ANCHOR",
            "INC N$XY_最终爆率 300",
            "\n",
        )
        adopted_anchor = install_managed_anchor_hook(
            legacy_anchor.text,
            "xy.optional.rage.core",
            "XY_EQUIP_MAKER_DROP_ANCHOR",
            "INC N$XY_最终爆率 300",
            "\n",
            legacy_package_ids=("xy.ops.rage-title",),
        )
        self.assertIn(
            "XYDP-ANCHOR-HOOK-BEGIN xy.optional.rage.core XY_EQUIP_MAKER_DROP_ANCHOR",
            adopted_anchor.text,
        )
        self.assertNotIn("XYDP-ANCHOR-HOOK-BEGIN xy.ops.rage-title", adopted_anchor.text)

    def test_remove_event_hook_requires_an_exact_unchanged_legacy_hash(self):
        old = install_event_hook(
            "[@AttackDamage]\n#IF\n#ACT\nBREAK\n",
            "xy.optional.rage.core",
            "AttackDamage",
            "#IF\n#ACT\n#CALL [\\玄渊功能\\狂暴\\狂暴核心.txt] @XY_RAGE_REFRESH",
            "\n",
        )
        removed = remove_event_hook(
            old.text,
            "xy.optional.rage.core",
            "AttackDamage",
            "\n",
            (old.content_hash,),
        )
        self.assertNotIn("XYDP-HOOK-BEGIN xy.optional.rage.core AttackDamage", removed.text)
        self.assertFalse(remove_event_hook(
            removed.text,
            "xy.optional.rage.core",
            "AttackDamage",
            "\n",
            (old.content_hash,),
        ).changed)
        with self.assertRaisesRegex(TextPatchError, "不在允许移除范围"):
            remove_event_hook(
                old.text,
                "xy.optional.rage.core",
                "AttackDamage",
                "\n",
                ("0" * 64,),
            )
        edited = old.text.replace("@XY_RAGE_REFRESH", "@XY_RAGE_CHANGED")
        with self.assertRaisesRegex(TextPatchError, "被手工修改"):
            remove_event_hook(
                edited,
                "xy.optional.rage.core",
                "AttackDamage",
                "\n",
                (old.content_hash,),
            )

    def test_event_hook_preserves_equipment_blocks_inserted_after_anchor(self):
        hook = (
            "MOV N$XY_RT_Drop 100\n"
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\n"
            "KILLMONBURSTRATE <$STR(N$XY_RT_Drop)>"
        )
        first = install_event_hook("[@AttackDamage]\n#ACT\nBREAK\n", "xy.runtime", "AttackDamage", hook, "\n")
        equipment = (
            "; XY-EQUIP-MAKER 爆率头盔: 爆率运行时+2000%\n"
            "#IF\nCHECKITEMW 爆率头盔 1\n#ACT\nINC N$XY_RT_Drop 2000\n"
        )
        extended = first.text.replace(
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\n",
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\n" + equipment,
        )
        second = install_event_hook(extended, "xy.runtime", "AttackDamage", hook, "\n")
        self.assertFalse(second.changed)
        self.assertEqual(second.text.count("; XY-EQUIP-MAKER 爆率头盔:"), 1)

    def test_event_hook_preserves_equipment_block_crlf_byte_shape(self):
        hook = "MOV N$XY_RT_Drop 100\r\n; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\r\nBREAK"
        first = install_event_hook("[@AttackDamage]\r\n#ACT\r\nBREAK\r\n", "xy.runtime", "AttackDamage", hook, "\r\n")
        equipment = (
            "; XY-EQUIP-MAKER 爆率头盔: 爆率运行时+2000%\r\n"
            "#IF\r\nCHECKITEMW 爆率头盔 1\r\n#ACT\r\nINC N$XY_RT_Drop 2000\r\n"
        )
        extended = first.text.replace(
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\r\n",
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\r\n" + equipment,
        )
        second = install_event_hook(extended, "xy.runtime", "AttackDamage", hook, "\r\n")
        self.assertFalse(second.changed)
        self.assertEqual(second.text, extended)

    def test_event_hook_preserves_multiple_equipment_blocks_in_original_order(self):
        hook = "MOV N$XY_RT_Drop 100\n; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\nBREAK"
        first = install_event_hook("[@AttackDamage]\n#ACT\nBREAK\n", "xy.runtime", "AttackDamage", hook, "\n")
        equipment = (
            "; XY-EQUIP-MAKER 爆率头盔: 爆率运行时+500%\n"
            "#IF\nCHECKITEMW 爆率头盔 1\n#ACT\nINC N$XY_RT_Drop 500\n\n"
            "; XY-EQUIP-MAKER 爆率头盔1: 爆率运行时+500%\n"
            "#IF\nCHECKITEMW 爆率头盔1 1\n#ACT\nINC N$XY_RT_Drop 500\n"
        )
        extended = first.text.replace(
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\n",
            "; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR\n" + equipment,
        )
        second = install_event_hook(extended, "xy.runtime", "AttackDamage", hook, "\n")
        third = install_event_hook(second.text, "xy.runtime", "AttackDamage", hook, "\n")
        self.assertFalse(second.changed)
        self.assertFalse(third.changed)
        self.assertEqual(third.text, extended)
        self.assertLess(third.text.index("CHECKITEMW 爆率头盔 1"), third.text.index("CHECKITEMW 爆率头盔1 1"))

    def test_managed_block_only_drops_declared_retired_equipment_anchor(self):
        old_content = (
            "[@XYDP_RecalcSustain]\n"
            "; XY_EQUIP_MAKER_HP_REGEN_ANCHOR\n"
            "; XY-EQUIP-MAKER 黄金圣物LV8: 每秒回血+1200\n"
            "#IF\nCHECKITEMW 黄金圣物LV8 1\n#ACT\nINC N$XY_SUS_HPPerSec 1200\n"
            "; XY_EQUIP_MAKER_LIFESTEAL_ANCHOR\n"
            "; XY-EQUIP-MAKER 吸血戒指: 吸血+10%\n"
            "#IF\nCHECKITEMW 吸血戒指 1\n#ACT\nINC N$XY_SUS_LifeSteal 10"
        )
        first = install_managed_block("", "xy.combat.sustain", old_content, "\n")
        new_content = (
            "[@XYDP_RecalcSustain]\n"
            "; XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR\n"
            "; XY_EQUIP_MAKER_LIFESTEAL_ANCHOR"
        )
        upgraded = install_managed_block(
            first.text,
            "xy.combat.sustain",
            new_content,
            "\n",
            retired_equipment_anchors=("XY_EQUIP_MAKER_HP_REGEN_ANCHOR",),
        )
        self.assertNotIn("N$XY_SUS_HPPerSec", upgraded.text)
        self.assertNotIn("CHECKITEMW 黄金圣物LV8 1", upgraded.text)
        self.assertIn("CHECKITEMW 吸血戒指 1", upgraded.text)
        self.assertIn("XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR", upgraded.text)

    def test_event_hook_still_rejects_non_equipment_manual_edit(self):
        hook = "MOV N$XY_RT_Drop 100\n; XY_EQUIP_MAKER_RUNTIME_DROP_ANCHOR"
        first = install_event_hook("[@AttackDamage]\n#ACT\nBREAK\n", "xy.runtime", "AttackDamage", hook, "\n")
        edited = first.text.replace("MOV N$XY_RT_Drop 100", "MOV N$XY_RT_Drop 999")
        with self.assertRaisesRegex(TextPatchError, "事件钩子被手工修改"):
            install_event_hook(edited, "xy.runtime", "AttackDamage", hook, "\n")

    def test_unique_line_rejects_conflicting_key(self):
        text = "测试NPC\tmap1\t10\t10\t名称\t0\t71\t0\r\n"
        with self.assertRaisesRegex(TextPatchError, "唯一键冲突"):
            add_unique_line(text, "测试NPC\tmap2\t20\t20\t名称\t0\t71\t0", [0], "\r\n")

    def test_exclusive_unique_line_replaces_every_other_npc_on_the_same_map(self):
        text = (
            "保留NPC\tmap1\t1\t1\t保留\t0\t8\t0\r\n"
            "旧NPC甲\tmap2\t10\t10\t旧甲\t0\t8\t0\r\n"
            "旧NPC乙\tmap2\t20\t20\t旧乙\t0\t8\t0\r\n"
            "尾部NPC\tmap3\t3\t3\t尾部\t0\t8\t0\r\n"
        )
        wanted = "赐福/地图二赐福点\tmap2\t30\t31\t地图二赐福点\t0\t8\t0"
        result = set_exclusive_unique_line(text, wanted, [1], "\r\n")
        self.assertTrue(result.changed)
        self.assertEqual(result.text.count("\tmap2\t"), 1)
        self.assertIn(wanted, result.text)
        self.assertIn("保留NPC\tmap1", result.text)
        self.assertIn("尾部NPC\tmap3", result.text)
        self.assertFalse(set_exclusive_unique_line(result.text, wanted, [1], "\r\n").changed)

    def test_mapinfo_flag_appends_whole_map_safe_without_erasing_existing_flags(self):
        source = "[XY_TEST|vx1 测试地图] NORANDOMMOVE SAFE(10,10,5)\r\n[OTHER|vx2 其他] DAY\r\n"
        result = ensure_mapinfo_flag(source, "xy_test", "SAFE")
        self.assertTrue(result.changed)
        self.assertEqual(
            result.text,
            "[XY_TEST|vx1 测试地图] NORANDOMMOVE SAFE(10,10,5) SAFE\r\n[OTHER|vx2 其他] DAY\r\n",
        )
        self.assertFalse(ensure_mapinfo_flag(result.text, "XY_TEST", "safe").changed)

    def test_mapinfo_flag_rejects_missing_or_duplicate_map_definition(self):
        with self.assertRaisesRegex(TextPatchError, "找不到地图代码"):
            ensure_mapinfo_flag("[OTHER|vx2 其他]\r\n", "XY_TEST", "SAFE")
        duplicate = "[XY_TEST|vx1 测试]\r\n[xy_test|vx2 重复]\r\n"
        with self.assertRaisesRegex(TextPatchError, "地图代码不唯一"):
            ensure_mapinfo_flag(duplicate, "XY_TEST", "SAFE")

    def test_mapinfo_title_replaces_only_title_and_preserves_alias_flags_and_crlf(self):
        source = "[XX105|XX105 巨龙盘踞之地] DAY SAFE(10,10,5)\r\n[XX106|vx106 旧名] DARK\r\n"
        result = set_mapinfo_display_name(source, "xx105", "沉没王座")
        self.assertTrue(result.changed)
        self.assertEqual(
            result.text,
            "[XX105|XX105 沉没王座] DAY SAFE(10,10,5)\r\n[XX106|vx106 旧名] DARK\r\n",
        )
        self.assertFalse(set_mapinfo_display_name(result.text, "XX105", "沉没王座").changed)

    def test_mapinfo_title_rejects_missing_duplicate_or_invalid_title(self):
        with self.assertRaises(TextPatchError):
            set_mapinfo_display_name("[OTHER|vx2 其他]\r\n", "XX105", "沉没王座")
        duplicate = "[XX105|XX105 旧名]\r\n[xx105|vx2 其他]\r\n"
        with self.assertRaises(TextPatchError):
            set_mapinfo_display_name(duplicate, "XX105", "沉没王座")
        with self.assertRaises(TextPatchError):
            set_mapinfo_display_name("[XX105|XX105 旧名]\r\n", "XX105", "坏[标题")

    def test_event_hook_is_inserted_immediately_after_unique_label(self):
        text = "[@PlayLogin]\r\n#IF\r\n#ACT\r\nBREAK\r\n[@Other]\r\n#ACT\r\nBREAK\r\n"
        result = install_event_hook(text, "xy.login", "PlayLogin", "DELAYGOTO 1 @XY_Login", "\r\n")
        expected = "[@PlayLogin]\r\n; XYDP-HOOK-BEGIN xy.login"
        self.assertIn(expected, result.text)
        self.assertEqual(result.text, install_event_hook(result.text, "xy.login", "PlayLogin", "DELAYGOTO 1 @XY_Login", "\r\n").text)

    def test_event_hook_rejects_missing_label(self):
        with self.assertRaisesRegex(TextPatchError, "找不到事件标签"):
            install_event_hook("[@Main]\n#ACT\nBREAK\n", "xy.login", "PlayLogin", "SENDMSG 6 X", "\n")

    def test_ensure_event_label_creates_missing_minimal_managed_stub_for_hook(self):
        self.assertTrue(hasattr(textpatch, "ensure_event_label"))
        source = "[@PlayDie]\r\n#IF\r\n#ACT\r\nBREAK\r\n"
        created = textpatch.ensure_event_label(source, "xy.combat.core", "PlayLogin", "\r\n")
        self.assertTrue(created.changed)
        self.assertIn("[@PlayLogin]", created.text)
        self.assertIn("XYDP-EVENT-STUB-BEGIN xy.combat.core PlayLogin", created.text)
        hooked = install_event_hook(created.text, "xy.combat.power", "PlayLogin", "DELAYGOTO 1 @XYDP_RecalcPower", "\r\n")
        self.assertIn("XYDP-HOOK-BEGIN xy.combat.power PlayLogin", hooked.text)

    def test_ensure_event_label_preserves_existing_target_event(self):
        self.assertTrue(hasattr(textpatch, "ensure_event_label"))
        source = "[@PlayLogin]\n#IF\n#ACT\nSENDMSG 6 existing\nBREAK\n"
        result = textpatch.ensure_event_label(source, "xy.combat.core", "PlayLogin", "\n")
        self.assertFalse(result.changed)
        self.assertEqual(result.text, source)

    def test_ensure_event_label_rejects_manual_change_to_its_stub(self):
        self.assertTrue(hasattr(textpatch, "ensure_event_label"))
        created = textpatch.ensure_event_label("", "xy.combat.core", "PlayLogin", "\n")
        edited = created.text.replace("BREAK", "SENDMSG 6 edited\nBREAK")
        with self.assertRaisesRegex(TextPatchError, "基础事件桩被手工修改"):
            textpatch.ensure_event_label(edited, "xy.combat.core", "PlayLogin", "\n")

    def test_ensure_callable_label_creates_braced_stub_and_hook_inside_braces(self):
        created = textpatch.ensure_callable_label("", "xy.rage", "XY_RAGE_UI_REFRESH", "\r\n")
        self.assertTrue(created.changed)
        self.assertIn("[@XY_RAGE_UI_REFRESH]\r\n{\r\n#IF", created.text)
        hooked = install_event_hook(
            created.text,
            "xy.ui.attr-overview",
            "XY_RAGE_UI_REFRESH",
            "#IF\n#ACT\nBREAK",
            "\r\n",
        )
        self.assertIn("[@XY_RAGE_UI_REFRESH]\r\n{\r\n; XYDP-HOOK-BEGIN", hooked.text)
        self.assertEqual(
            hooked.text,
            install_event_hook(
                hooked.text,
                "xy.ui.attr-overview",
                "XY_RAGE_UI_REFRESH",
                "#IF\n#ACT\nBREAK",
                "\r\n",
            ).text,
        )

    def test_ensure_callable_label_safely_wraps_legacy_empty_stub_with_hook(self):
        source = (
            "[@XY_RAGE_UI_REFRESH]\r\n"
            "; XYDP-HOOK-BEGIN xy.ui.attr-overview XY_RAGE_UI_REFRESH "
            "SHA256=6beaf55aaac3f6dd2a37ab23147ee5b3137de489ea14d2f767a3245033fb97cc\r\n"
            "#IF\r\n#ACT\r\n#CALL [\\x.txt] @DRAW\r\n"
            "; XYDP-HOOK-END xy.ui.attr-overview XY_RAGE_UI_REFRESH\r\n"
            "#IF\r\n#ACT\r\nBREAK\r\n"
        )
        result = textpatch.ensure_callable_label(source, "xy.rage", "XY_RAGE_UI_REFRESH", "\r\n")
        self.assertTrue(result.changed)
        self.assertIn("[@XY_RAGE_UI_REFRESH]\r\n{\r\n; XYDP-HOOK-BEGIN", result.text)
        self.assertTrue(result.text.rstrip().endswith("}"))

    def test_ensure_callable_label_rejects_unknown_unbraced_body(self):
        source = "[@XY_RAGE_UI_REFRESH]\n#IF\n#ACT\nSENDMSG 6 unknown\nBREAK\n"
        with self.assertRaisesRegex(TextPatchError, "无法安全迁移"):
            textpatch.ensure_callable_label(source, "xy.rage", "XY_RAGE_UI_REFRESH", "\n")

    def test_multiple_event_hooks_preserve_install_order(self):
        text = "[@AttackDamage]\n#ACT\nBREAK\n"
        first = install_event_hook(text, "xy.pve", "AttackDamage", "MOV N$PVE 0", "\n")
        second = install_event_hook(first.text, "xy.execute", "AttackDamage", "LARGE N$TAIL 0", "\n")
        self.assertLess(second.text.index("XYDP-HOOK-BEGIN xy.pve"), second.text.index("XYDP-HOOK-BEGIN xy.execute"))
        self.assertLess(second.text.index("XYDP-HOOK-BEGIN xy.execute"), second.text.index("#ACT"))


if __name__ == "__main__":
    unittest.main()
