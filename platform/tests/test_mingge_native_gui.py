from types import SimpleNamespace
import unittest
from unittest.mock import patch

from xydp.gui import PlatformApp


class MinggeNativeGuiTests(unittest.TestCase):
    def test_install_button_runs_fresh_preflight_without_requiring_a_separate_click(self) -> None:
        plan = SimpleNamespace(blockers=())
        preflight_calls: list[bool] = []

        def preflight(*, show_success: bool = True):
            preflight_calls.append(show_success)
            return plan

        app = SimpleNamespace(
            current_mingge_native_p3_color_test_plan=None,
            mingge_native_p3_color_test_preflight=preflight,
        )
        with (
            patch("xydp.gui.messagebox.askyesno", return_value=False) as askyesno,
            patch("xydp.gui.messagebox.showwarning") as showwarning,
        ):
            PlatformApp.mingge_native_p3_color_test_install(app)

        self.assertEqual(preflight_calls, [False])
        askyesno.assert_called_once()
        showwarning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
