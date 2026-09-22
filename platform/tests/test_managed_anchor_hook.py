from __future__ import annotations

import unittest

from xydp.textpatch import (
    TextPatchError,
    install_managed_anchor_hook,
    remove_managed_anchor_hook,
)


class ManagedAnchorHookTests(unittest.TestCase):
    def setUp(self):
        self.anchor = "XY_EQUIP_MAKER_DROP_ANCHOR"
        self.text = (
            "; XYDP-EXTENSION-BEGIN DROP\r\n"
            f"; {self.anchor}\r\n"
            "INC N$原有值 1\r\n"
            "; XYDP-EXTENSION-END DROP\r\n"
        )

    def test_insert_is_idempotent_and_keeps_existing_anchor_content(self):
        first = install_managed_anchor_hook(
            self.text, "xy.ops.rage-title", self.anchor, "INC N$XY_最终爆率 300", "\r\n"
        )
        second = install_managed_anchor_hook(
            first.text, "xy.ops.rage-title", self.anchor, "INC N$XY_最终爆率 300", "\r\n"
        )

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(first.text, second.text)
        self.assertIn("XYDP-ANCHOR-HOOK-BEGIN xy.ops.rage-title XY_EQUIP_MAKER_DROP_ANCHOR", first.text)
        self.assertIn("INC N$原有值 1", first.text)

    def test_multiple_packages_are_ordered_after_the_same_anchor(self):
        rage = install_managed_anchor_hook(
            self.text, "xy.ops.rage-title", self.anchor, "INC N$XY_最终爆率 300", "\r\n"
        )
        donate = install_managed_anchor_hook(
            rage.text, "xy.ops.donate-title", self.anchor, "INC N$XY_最大爆率 20", "\r\n"
        )

        self.assertLess(
            donate.text.index("XYDP-ANCHOR-HOOK-BEGIN xy.ops.rage-title"),
            donate.text.index("XYDP-ANCHOR-HOOK-BEGIN xy.ops.donate-title"),
        )
        self.assertLess(
            donate.text.index("XYDP-ANCHOR-HOOK-BEGIN xy.ops.donate-title"),
            donate.text.index("INC N$原有值 1"),
        )

    def test_canonical_hook_stays_after_unmanaged_content_and_before_existing_hook(self):
        existing = install_managed_anchor_hook(
            f"; {self.anchor}\r\n", "xy.other", self.anchor, "INC N$XY_OTHER 1", "\r\n"
        ).text.replace(
            f"; {self.anchor}\r\n",
            f"; {self.anchor}\r\nINC N$原有值 1\r\n",
            1,
        )
        first = install_managed_anchor_hook(
            existing,
            "xy.initial-camp.seven-npcs",
            self.anchor,
            "INC N$XY_SPONSOR 1",
            "\r\n",
            canonical_before_existing_hooks=True,
        )
        second = install_managed_anchor_hook(
            first.text,
            "xy.initial-camp.seven-npcs",
            self.anchor,
            "INC N$XY_SPONSOR 1",
            "\r\n",
            canonical_before_existing_hooks=True,
        )

        self.assertLess(first.text.index("INC N$原有值 1"), first.text.index("xy.initial-camp.seven-npcs"))
        self.assertLess(first.text.index("xy.initial-camp.seven-npcs"), first.text.index("xy.other"))
        self.assertEqual(second.text, first.text)
        self.assertFalse(second.changed)

    def test_unmodified_owned_block_can_be_upgraded(self):
        first = install_managed_anchor_hook(
            self.text, "xy.ops.rage-title", self.anchor, "INC N$XY_最终爆率 300", "\r\n"
        )
        upgraded = install_managed_anchor_hook(
            first.text, "xy.ops.rage-title", self.anchor, "INC N$XY_最终爆率 350", "\r\n"
        )

        self.assertTrue(upgraded.changed)
        self.assertIn("INC N$XY_最终爆率 350", upgraded.text)
        self.assertNotIn("INC N$XY_最终爆率 300", upgraded.text)

    def test_manual_edit_blocks_upgrade(self):
        first = install_managed_anchor_hook(
            self.text, "xy.ops.rage-title", self.anchor, "INC N$XY_最终爆率 300", "\r\n"
        )
        edited = first.text.replace("INC N$XY_最终爆率 300", "INC N$XY_最终爆率 999")

        with self.assertRaisesRegex(TextPatchError, "锚点钩子被手工修改"):
            install_managed_anchor_hook(
                edited, "xy.ops.rage-title", self.anchor, "INC N$XY_最终爆率 300", "\r\n"
            )

    def test_missing_or_duplicate_anchor_is_rejected(self):
        with self.assertRaisesRegex(TextPatchError, "找不到受管锚点"):
            install_managed_anchor_hook("", "xy.ops.rage-title", self.anchor, "INC N$A 1", "\r\n")
        duplicate = self.text + f"; {self.anchor}\r\n"
        with self.assertRaisesRegex(TextPatchError, "受管锚点不唯一"):
            install_managed_anchor_hook(duplicate, "xy.ops.rage-title", self.anchor, "INC N$A 1", "\r\n")

    def test_remove_owned_or_legacy_hook_is_safe_and_idempotent(self):
        old = install_managed_anchor_hook(
            self.text, "xy.ops.donate-title", self.anchor, "INC N$XY_最大爆率 20", "\r\n"
        )
        removed = remove_managed_anchor_hook(
            old.text, "xy.initial-camp.seven-npcs", self.anchor,
            legacy_package_ids=("xy.ops.donate-title",),
        )
        second = remove_managed_anchor_hook(
            removed.text, "xy.initial-camp.seven-npcs", self.anchor,
            legacy_package_ids=("xy.ops.donate-title",),
        )

        self.assertTrue(removed.changed)
        self.assertNotIn("xy.ops.donate-title", removed.text)
        self.assertFalse(second.changed)
        self.assertEqual(second.text, removed.text)

    def test_remove_rejects_manual_edit(self):
        old = install_managed_anchor_hook(
            self.text, "xy.ops.donate-title", self.anchor, "INC N$XY_最大爆率 20", "\r\n"
        ).text.replace("INC N$XY_最大爆率 20", "INC N$XY_最大爆率 999")

        with self.assertRaisesRegex(TextPatchError, "锚点钩子被手工修改，禁止移除"):
            remove_managed_anchor_hook(old, "xy.ops.donate-title", self.anchor)


if __name__ == "__main__":
    unittest.main()
