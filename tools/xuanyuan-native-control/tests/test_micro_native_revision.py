"""Keep the native probe's self-drawn Rz controls outside message-action claims."""
import pytest

from test_micro_server_window import COMPONENTS, MicroDesktop
from test_native_window import module
from test_stack_component_window import action_request, request


@pytest.mark.parametrize('cls', ['TRzPageControl', 'TRzCheckBox', 'TRzBitBtn'])
def test_self_drawn_raize_message_action_is_rejected_before_dispatch(tmp_path, monkeypatch, cls):
    component = COMPONENTS[1]
    desktop = MicroDesktop(component, monkeypatch)
    action = desktop.raize_action(cls)
    req = action_request(tmp_path, desktop, component, action)
    with pytest.raises(ValueError, match='Control class'):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.events
    assert not (tmp_path / 'action').exists()


def test_self_drawn_controls_stay_observable_without_common_tab_messages(tmp_path, monkeypatch):
    component = COMPONENTS[1]
    desktop = MicroDesktop(component, monkeypatch)
    for cls in ('TRzPageControl', 'TRzCheckBox', 'TRzBitBtn'):
        desktop.raize_action(cls)
    desktop.checks[13] = 1
    original = desktop.native.user.SendMessageTimeoutW

    def no_common_tab_messages(hwnd, message, *args):
        if message in (0x1304, 0x130B, 0x133C, 0x1330):
            raise AssertionError('Self-drawn TRzPageControl is not a common-control tab')
        return original(hwnd, message, *args)

    desktop.native.user.SendMessageTimeoutW = no_common_tab_messages
    result = module().run_window(request(tmp_path, component), backend=desktop)
    controls = {item['class']: item for item in result['target']['controls']}
    assert {'TRzPageControl', 'TRzCheckBox', 'TRzBitBtn'} <= controls.keys()
    assert 'tabs' not in controls['TRzPageControl'] and 'selectedText' not in controls['TRzPageControl']
    assert controls['TRzCheckBox']['check'] == 1 and desktop.check_reads
    assert result['screenshot'] and not result['actionAttempted'] and not desktop.messages


def test_self_drawn_checkbox_can_use_existing_guarded_visual_delivery_without_business_claim(tmp_path, monkeypatch):
    component = COMPONENTS[1]
    desktop = MicroDesktop(component, monkeypatch)
    desktop.raize_action('TRzCheckBox')
    visual = {'kind': 'visual-click', 'x': 50, 'y': 60, 'button': 'left'}
    result = module().run_window(action_request(tmp_path, desktop, component, visual), backend=desktop)
    assert desktop.events == [('down', 'mouse', 'left'), ('up', 'mouse', 'left')]
    assert not desktop.messages and result['dispatch']['mode'] == 'SendInput' and result['dispatch']['accepted']
    assert result['actionAttempted'] and not result['readbackVerified'] and not result['businessSaveVerified']
