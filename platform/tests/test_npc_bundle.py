from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
import sqlite3
import zipfile

from xydp.npc_bundle import (
    BundleShadowWorkspace,
    NUCLEUS_LOOKS,
    NpcBundleService,
    TitleDefinition,
    allocate_title_shapes,
    choose_npc_positions,
    stage_nuclei,
    workbook_has_usable_dimension,
)
from xydp.installer import PlannedChange


ZIP = Path(r"C:\Users\Administrator\Downloads\艾尔登法环_全NPC平台填写_V2.1_20260920.zip")


class NpcBundleDiscoveryTests(unittest.TestCase):
    def test_zip_is_classified_by_relative_path_and_excludes_final_scope(self):
        manifest = NpcBundleService(Path(r"E:\XuanYuanDevPlatform")).inspect_bundle(ZIP)

        self.assertEqual(manifest.source_kind, "zip")
        self.assertEqual(manifest.file_count, 66)
        self.assertEqual(manifest.xlsx_count, 64)
        self.assertEqual(manifest.active_xlsx_count, 62)
        self.assertEqual(
            manifest.category_counts,
            {
                "audit": 1,
                "initial_camp": 6,
                "skill_upgrade": 1,
                "weapon_enchant": 1,
                "global": 8,
                "seal_catchup": 9,
                "independent_title": 6,
                "synthesis": 16,
                "rebirth": 4,
                "main_title": 10,
            },
        )
        self.assertEqual(
            {item.reason for item in manifest.excluded},
            {"命格按用户决定暂缓", "旧营地转生入口保持停用"},
        )
        self.assertTrue(all("\\" not in item.relative_path for item in manifest.documents))

    def test_directory_and_zip_have_the_same_relative_documents(self):
        service = NpcBundleService(Path(r"E:\XuanYuanDevPlatform"))
        with tempfile.TemporaryDirectory(prefix="xydp-bundle-directory-") as temp:
            extracted_root = service.materialize_bundle(ZIP, Path(temp))
            archive = service.inspect_bundle(ZIP)
            directory = service.inspect_bundle(extracted_root)

            self.assertEqual(
                [item.relative_path for item in archive.documents],
                [item.relative_path for item in directory.documents],
            )
            self.assertEqual(archive.category_counts, directory.category_counts)

    def test_duplicate_or_missing_required_documents_are_blockers(self):
        service = NpcBundleService(Path(r"E:\XuanYuanDevPlatform"))
        manifest = service.inspect_bundle(ZIP)

        self.assertEqual(manifest.blockers, ())
        self.assertEqual(len(manifest.by_category("synthesis")), 16)
        self.assertEqual(len(manifest.by_category("main_title")), 10)

    def test_content_audit_matches_the_filled_v21_bundle(self):
        audit = NpcBundleService(Path(r"E:\XuanYuanDevPlatform")).audit_content(
            ZIP, Path(r"D:\MirServer")
        )

        self.assertEqual(audit.seal_levels, 255)
        self.assertEqual(audit.rebirth_levels, 20)
        self.assertEqual(audit.main_title_levels, 100)
        self.assertEqual(audit.independent_title_levels, 12)
        self.assertEqual(audit.synthesis_recipes, 38)
        self.assertEqual(audit.skill_chains, 5)
        self.assertEqual(audit.skill_levels, 45)
        self.assertEqual(audit.collection_items, 619)
        self.assertEqual(audit.collection_groups, 46)
        # The five nuclei are the only references the bundle may need to
        # create.  Before installation all five are absent; after a successful
        # installation none are absent.  The content audit must be valid in
        # both target states and must never hide another missing item.
        self.assertLessEqual(
            set(audit.missing_item_names),
            {f"群星之核LV{level}" for level in range(1, 6)},
        )
        self.assertEqual(audit.duplicate_item_names, ())
        self.assertEqual(audit.blockers, ())

    def test_materialized_workbooks_have_usable_dimensions_and_keep_relative_identity(self):
        service = NpcBundleService(Path(r"E:\XuanYuanDevPlatform"))
        with tempfile.TemporaryDirectory() as temp:
            root = service.materialize_bundle(ZIP, Path(temp))
            manifest = service.inspect_bundle(root)

            self.assertEqual(manifest.blockers, ())
            self.assertEqual(manifest.active_xlsx_count, 62)
            duplicate_names = [
                item for item in manifest.documents if item.filename == "22_称号晋升.xlsx"
            ]
            self.assertEqual(len(duplicate_names), 16)
            self.assertEqual(len({item.relative_path for item in duplicate_names}), 16)
            self.assertTrue(
                all(workbook_has_usable_dimension(root / item.relative_path) for item in manifest.documents)
            )


class NpcBundleFoundationTests(unittest.TestCase):
    def test_shadow_workspace_composes_overlapping_changes_without_touching_live_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            server = base / "live-server"
            client = base / "live-client"
            launcher = base / "live-launcher"
            (server / "Mir200" / "Envir").mkdir(parents=True)
            (server / "Mir200" / "Map").mkdir(parents=True)
            (server / "Mud2" / "DB").mkdir(parents=True)
            (client / "data").mkdir(parents=True)
            (launcher / "补丁文件夹" / "Data").mkdir(parents=True)
            (server / "Mir200" / "M2Server.exe").write_bytes(b"engine")
            (server / "Mir200" / "Envir" / "MapInfo.txt").write_bytes(b"map")
            live = server / "Mir200" / "Envir" / "QFunction-0.txt"
            live.write_bytes(b"base")

            shadow = BundleShadowWorkspace.create(
                server=server,
                client=client,
                launcher=launcher,
                working_root=base / "shadow",
            )
            shadow.apply_changes((
                PlannedChange("Mir200/Envir/QFunction-0.txt", b"base", b"first", "one", "p1"),
            ))
            shadow.apply_changes((
                PlannedChange("Mir200/Envir/QFunction-0.txt", b"first", b"second", "two", "p2"),
            ))

            self.assertEqual(live.read_bytes(), b"base")
            final = shadow.final_changes()
            self.assertEqual(len(final), 1)
            self.assertEqual(final[0].before, b"base")
            self.assertEqual(final[0].after, b"second")

    def test_shadow_workspace_rejects_map_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            server = base / "live-server"
            (server / "Mir200" / "Envir").mkdir(parents=True)
            (server / "Mir200" / "Map").mkdir(parents=True)
            (server / "Mud2" / "DB").mkdir(parents=True)
            (server / "Mir200" / "M2Server.exe").write_bytes(b"engine")
            (server / "Mir200" / "Envir" / "MapInfo.txt").write_bytes(b"map")
            (server / "Mir200" / "Map" / "one.map").write_bytes(b"map-bytes")
            shadow = BundleShadowWorkspace.create(
                server=server,
                client=None,
                launcher=None,
                working_root=base / "shadow",
            )

            with self.assertRaisesRegex(ValueError, "地图文件不在本轮范围"):
                shadow.apply_changes((
                    PlannedChange("Mir200/Map/one.map", b"map-bytes", b"changed", "bad", "p"),
                ))

    def test_title_allocator_reuses_exact_definition_and_remaps_only_occupied_shape(self):
        existing = (
            TitleDefinition("漂泊余烬", 100, 10, 10, 10, 1000, 1000, 0),
            TitleDefinition("既有无关称号", 40, 1, 1, 1, 1, 1, 0),
        )
        requested = (
            TitleDefinition("漂泊余烬", 100, 10, 10, 10, 1000, 1000, 0),
            TitleDefinition("转生11重", 40, 0, 0, 0, 0, 0, 0),
            TitleDefinition("新称号", 110, 20, 20, 20, 2000, 2000, 1),
        )

        mapping = allocate_title_shapes(existing, requested, fallback_start=212)

        self.assertEqual(mapping["漂泊余烬"], 100)
        self.assertEqual(mapping["转生11重"], 212)
        self.assertEqual(mapping["新称号"], 110)

    def test_title_allocator_rejects_same_name_with_different_definition(self):
        existing = (TitleDefinition("同名", 100, 1, 1, 1, 1, 1, 0),)
        requested = (TitleDefinition("同名", 100, 2, 1, 1, 1, 1, 0),)

        with self.assertRaisesRegex(ValueError, "同名称号定义不一致"):
            allocate_title_shapes(existing, requested)

    def test_nuclei_are_idempotent_and_have_only_requested_native_slot_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "ApexM2.DB"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE StdItems ("
                "Idx INTEGER, Name TEXT, StdMode INTEGER, Shape INTEGER, Weight INTEGER, "
                "Anicount INTEGER, Source INTEGER, Reserved INTEGER, Looks INTEGER, DuraMax INTEGER, "
                "Ac INTEGER, Ac2 INTEGER, Mac INTEGER, Mac2 INTEGER, Dc INTEGER, Dc2 INTEGER, "
                "Mc INTEGER, Mc2 INTEGER, Sc INTEGER, Sc2 INTEGER, Need INTEGER, NeedLevel INTEGER, "
                "Price INTEGER, Stock INTEGER, Color INTEGER, OverLap INTEGER, HP INTEGER, MP INTEGER, "
                "Light INTEGER, Horse INTEGER, Element INTEGER, Expand1 INTEGER, Expand2 INTEGER, "
                "InsuranceCurrency INTEGER, InsuranceGold INTEGER, Expand3 INTEGER, Expand4 INTEGER, "
                "Expand5 INTEGER, Asc INTEGER, Asc2 INTEGER, Arc INTEGER, Arc2 INTEGER, Mpc INTEGER, "
                "Mpc2 INTEGER, Job INTEGER, Element26 INTEGER, CustomItem INTEGER)"
            )
            connection.commit()
            connection.close()

            first, created = stage_nuclei(database.read_bytes())
            second, created_again = stage_nuclei(first)

            self.assertEqual(created, tuple(NUCLEUS_LOOKS))
            self.assertEqual(created_again, ())
            self.assertEqual(first, second)
            staged = Path(temp) / "staged.db"
            staged.write_bytes(first)
            connection = sqlite3.connect(staged)
            try:
                rows = connection.execute(
                    "SELECT Name,StdMode,Looks,OverLap,Expand1,Dc,Dc2,Mc,Mc2,Sc,Sc2,HP,MP "
                    "FROM StdItems ORDER BY Idx"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(len(rows), 5)
            for level, row in enumerate(rows, 1):
                self.assertEqual(row[:5], (f"群星之核LV{level}", 48, NUCLEUS_LOOKS[f"群星之核LV{level}"], 4, 9))
                self.assertEqual(row[5:], (0, 0, 0, 0, 0, 0, 0, 0))

    def test_position_allocator_scans_from_center_and_keeps_safe_spacing(self):
        positions = choose_npc_positions(
            width=21,
            height=21,
            count=5,
            occupied={(10, 10), (10, 9)},
            is_walkable=lambda x, y: (x + y) % 2 == 0,
            minimum_distance=3,
        )

        self.assertEqual(len(positions), 5)
        self.assertEqual(len(set(positions)), 5)
        self.assertTrue(all((x + y) % 2 == 0 for x, y in positions))
        self.assertTrue(all(point not in {(10, 10), (10, 9)} for point in positions))
        for index, left in enumerate(positions):
            for right in positions[index + 1:]:
                self.assertGreaterEqual(max(abs(left[0] - right[0]), abs(left[1] - right[1])), 3)


if __name__ == "__main__":
    unittest.main()
