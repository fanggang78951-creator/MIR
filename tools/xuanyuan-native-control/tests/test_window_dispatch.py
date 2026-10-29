import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wzl_blackbox import native_control as control


class WindowDispatchTests(unittest.TestCase):
    def test_window_commands_are_public_without_losing_existing_contracts(self):
        self.assertTrue({'window-observe', 'window-action'}.issubset(control.COMMANDS))
        self.assertTrue({'engine-parameter', 'm2-reload', 'game-input', 'launcher-build'}.issubset(control.COMMANDS))

    def test_window_request_uses_own_adapter_not_game_or_lab_parameter(self):
        request = {'schemaVersion': 1, 'command': 'window-action', 'arguments': {'pid': 32096}}
        module = SimpleNamespace(validate_request=Mock(return_value={}),
                                 run_window=Mock(return_value={'actionAcknowledged': True}))
        with patch.dict(sys.modules, {'wzl_blackbox.native_window': module}):
            result = control.run(request)
        self.assertTrue(result['actionAcknowledged'])
        module.validate_request.assert_called_once_with(request)
        module.run_window.assert_called_once_with(request)

    def test_capabilities_explain_generic_controls_and_business_verification(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(control.main(['capabilities']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['version'], '1.1.24')
        self.assertEqual(result['nativeWindowCommands'], ['window-observe', 'window-action'])
        self.assertIn('M2', result['nativeWindowScope'])
        self.assertIn('LoginSrv', result['nativeWindowScope'])
        for component in ('DBServer', 'RunGate', 'SelGate'):
            self.assertIn(component, result['nativeWindowScope'])
        self.assertTrue(result['nativeInputRequiresFreshObservation'])
        self.assertFalse(result['gameAcceptancePerformed'])


if __name__ == '__main__':
    unittest.main()
