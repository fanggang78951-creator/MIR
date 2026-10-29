import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wzl_blackbox import native_control as control


class GameDispatchTests(unittest.TestCase):
    def test_game_commands_advertised_without_replacing_legacy(self):
        self.assertTrue({'game-inspect', 'game-observe', 'game-input'}.issubset(control.COMMANDS))
        self.assertTrue({'inspect', 'm2-reload', 'launcher-build', 'm2-client-build'}.issubset(control.COMMANDS))

    def test_game_validation_uses_adapter_contract(self):
        request = {'schemaVersion': 1, 'command': 'game-observe', 'arguments': {}}
        adapter = SimpleNamespace(validate_request=Mock(return_value={'command': 'game-observe', 'gameRequest': request}))
        with patch.dict(sys.modules, {'wzl_blackbox.native_game': adapter}):
            self.assertEqual(control.validate_request(request)['gameRequest'], request)
        adapter.validate_request.assert_called_once_with(request)

    def test_game_run_delegates_to_same_native_control(self):
        request = {'schemaVersion': 1, 'command': 'game-inspect', 'arguments': {}}
        adapter = SimpleNamespace(validate_request=Mock(return_value={'command': 'game-inspect'}), run_game=Mock(return_value={'readOnly': True, 'windows': []}))
        with patch.dict(sys.modules, {'wzl_blackbox.native_game': adapter}):
            self.assertTrue(control.run(request)['readOnly'])
        adapter.run_game.assert_called_once_with(request)


if __name__ == '__main__':
    unittest.main()
