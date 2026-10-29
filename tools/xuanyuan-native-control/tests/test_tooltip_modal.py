"""Exact native popup tooltips are observable decorations, not owned modals."""
import json
from pathlib import Path

import pytest

from test_native_window import Desktop, action_request, module, relationship_desktop, request


def popup(*, hwnd=400, cls='tooltips_class32', style=0x94000002, parent=345, owner=345):
    return {'hwnd': hwnd, 'parent': parent, 'owner': owner, 'class': cls, 'title': '',
            'style': style, 'rect': [760, 390, 822, 407], 'visible': True, 'enabled': True}


def with_live_forms(tmp_path, forms, action=None):
    desktop = Desktop()
    req = action_request(tmp_path, desktop, action or {'kind': 'key', 'key': 'HOME'})
    live = relationship_desktop(forms)
    desktop.snapshot, desktop.native_forms = live.snapshot, live.native_forms
    return desktop, req


@pytest.mark.parametrize('parent,owner', [(345, 345), (0, 345), (345, 0)])
def test_exact_popup_tooltip_keeps_forms_and_allows_target_screenshot(tmp_path, parent, owner):
    tooltip = popup(parent=parent, owner=owner)
    desktop = relationship_desktop([tooltip])
    result = module().run_window(request(tmp_path), backend=desktop)
    assert result['target']['blockingWindows'] == []
    assert result['screenshot']['hwnd'] == 345
    observed_tooltip = next(item for item in result['forms'] if item['hwnd'] == 400)
    assert observed_tooltip == tooltip
    assert not desktop.events and not result['actionAttempted']


def test_tooltip_exclusion_retains_one_action_and_existing_receipt_contract(tmp_path):
    desktop = relationship_desktop([popup()])
    req = action_request(tmp_path, desktop, {'kind': 'key', 'key': 'HOME'})
    result = module().run_window(req, backend=desktop)
    assert desktop.events == [('down', 'key', 'HOME'), ('up', 'key', 'HOME')]
    assert result['actionAttempted'] and result['dispatch']['accepted']
    assert result['screenshot']['hwnd'] == 345 and result['target']['blockingWindows'] == []
    assert any(item['hwnd'] == 400 for item in result['forms'])
    assert Path(result['observationReceipt']).is_file() and len(result['observationSha256']) == 64
    assert not desktop.held and 'guardEvidence' not in result


@pytest.mark.parametrize('cls', ['#32770', 'TCustomWarning', 'UnknownPopup'])
def test_tooltip_cannot_hide_a_real_owned_modal_even_with_empty_title_and_tiny_area(tmp_path, cls):
    modal = popup(hwnd=401, cls=cls, style=0x90C800C4)
    modal['rect'] = [700, 400, 701, 401]
    desktop, req = with_live_forms(tmp_path, [popup(), modal])
    target = desktop.snapshot(12, 345)
    assert [item['hwnd'] for item in target['blockingWindows']] == [401]
    with pytest.raises(ValueError, match='modal'):
        module().run_window(req, backend=desktop)
    assert not desktop.events


@pytest.mark.parametrize('cls', ['Tooltips_class32', 'tooltips_class32Extra', 'SysShadow'])
def test_nonexact_classes_and_owned_shadow_keep_original_modal_protection(tmp_path, cls):
    desktop, req = with_live_forms(tmp_path, [popup(cls=cls)])
    assert [item['hwnd'] for item in desktop.snapshot(12, 345)['blockingWindows']] == [400]
    with pytest.raises(ValueError, match='modal'):
        module().run_window(req, backend=desktop)
    assert not desktop.events


def test_exact_tooltip_without_popup_style_is_not_exempted(tmp_path):
    desktop, req = with_live_forms(tmp_path, [popup(style=0x14000002)])
    assert [item['hwnd'] for item in desktop.snapshot(12, 345)['blockingWindows']] == [400]
    with pytest.raises(ValueError, match='modal'):
        module().run_window(req, backend=desktop)
    assert not desktop.events


def test_existing_child_window_rule_and_unowned_shadow_stay_observable(tmp_path):
    child = popup(style=0x54000002)
    shadow = popup(hwnd=401, cls='SysShadow', style=0x94000000, parent=0, owner=0)
    desktop = relationship_desktop([child, shadow])
    result = module().run_window(request(tmp_path), backend=desktop)
    assert result['target']['blockingWindows'] == []
    assert {item['hwnd'] for item in result['forms']} == {345, 400, 401}
    assert any(item['hwnd'] == 400 for item in result['target']['controls'])
    assert result['screenshot']['hwnd'] == 345 and not desktop.events


def test_tooltip_exclusion_never_authorizes_a_disabled_target(tmp_path):
    desktop = relationship_desktop([popup()])
    req = action_request(tmp_path, desktop, {'kind': 'key', 'key': 'HOME'})
    backend = desktop.snapshot.__self__
    original = backend._basic

    def basic(hwnd):
        item = original(hwnd)
        if hwnd == 345:
            item['enabled'] = False
        return item

    backend._basic = basic
    with pytest.raises(ValueError):
        module().run_window(req, backend=desktop)
    failure = json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))
    assert not failure['actionAttempted'] and not desktop.events


@pytest.mark.parametrize('guard', ['point', 'focus'])
def test_tooltip_exclusion_does_not_bypass_point_or_keyboard_focus_guards(tmp_path, guard):
    desktop = relationship_desktop([popup()])
    action = {'kind': 'visual-click', 'x': 50, 'y': 60} if guard == 'point' else {'kind': 'key', 'key': 'HOME'}
    req = action_request(tmp_path, desktop, action)
    if guard == 'point':
        desktop.root_at = lambda point: 400
    else:
        desktop.focus_in_form = lambda hwnd: False
    with pytest.raises(ValueError, match='ownership' if guard == 'point' else 'Keyboard focus'):
        module().run_window(req, backend=desktop)
    assert not desktop.events


def test_tooltip_exclusion_does_not_allow_foreign_process_control_input(tmp_path):
    desktop = relationship_desktop([popup()])
    req = action_request(tmp_path, desktop, {'kind': 'button', 'controlHwnd': 14,
                                            'expectedClass': 'TButton', 'expectedText': '保存'})
    backend = desktop.snapshot.__self__

    def process(hwnd, result):
        result._obj.value = 88 if hwnd == 14 else 12
        return 1

    backend.user.GetWindowThreadProcessId = process
    backend.user.GetAncestor = lambda hwnd, flag: 345 if hwnd == 14 else 0
    desktop.control_in_form = backend.control_in_form
    with pytest.raises(ValueError, match='Control process/ancestor'):
        module().run_window(req, backend=desktop)
    assert not desktop.events
