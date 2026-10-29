"""Exact GameCenter class aliases at the real snapshot/hosting OS boundary.

No live window, menu, service or configuration is used by this module.
"""
import pytest

from test_native_window import module
from test_stack_component_window import ComponentDesktop, COMPONENTS, request


HOSTED_COMPONENTS = [
    (r'D:\MirServer\Mir200\M2Server.exe',
     '1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A',
     'GameCenterHostedM2'),
    (r'D:\MirServer\LoginSrv\LoginSrv.exe',
     '1CC15D5A3848E2EB3DD2FB52947331527D8708C165F3266D5AC7DA80C8D9BC57',
     'GameCenterHostedLoginSrv'),
    *COMPONENTS,
]
COMPONENT_NAMES = ['M2', 'LoginSrv', 'DBServer', 'RunGate', 'SelGate']
MENU_ACTION = {'kind': 'menu', 'path': ['管理', '设置'], 'synchronous': True}


def action_from_observation(tmp_path, component, observed):
    result = request(tmp_path, component, command='window-action', name='action')
    result['arguments'].update(observationReceipt=observed['observationReceipt'],
                               observationSha256=observed['observationSha256'],
                               action=dict(MENU_ACTION))
    return result


@pytest.mark.parametrize('component', HOSTED_COMPONENTS, ids=COMPONENT_NAMES)
@pytest.mark.parametrize('host_class', ['TfrmMain', 'TFrmMain'])
def test_exact_host_classes_observe_and_dispatch_one_native_menu(tmp_path, component, host_class):
    desktop = ComponentDesktop(component, hosted=True)
    desktop.nodes[700]['class'] = host_class
    observed = module().run_window(request(tmp_path, component), backend=desktop)
    host = observed['target']['hosting']
    assert host['class'] == host_class
    assert host['ancestorChain'][-1]['class'] == host_class
    assert host['kind'] == component[2]
    assert observed['screenshot']
    assert not desktop.messages

    result = module().run_window(action_from_observation(tmp_path, component, observed), backend=desktop)
    assert desktop.menu_commands == [42]
    assert desktop.messages == [(345, 0x111, 2, 60000)]
    assert result['actionAttempted'] and result['dispatch']['handlerAcknowledged']
    assert not result['businessSaveVerified']
    assert result['recovery'] == {'foregroundRestored': True, 'cursorRestored': True}


@pytest.mark.parametrize('host_class', ['tfrmmain', 'TFRMMAIN', 'Tfrmmain', 'TFrmMainExtra'])
def test_other_host_class_spellings_are_rejected_before_native_input(tmp_path, host_class):
    component = HOSTED_COMPONENTS[0]
    desktop = ComponentDesktop(component, hosted=True)
    desktop.nodes[700]['class'] = host_class
    with pytest.raises(PermissionError, match='verified GameCenter'):
        module().run_window(request(tmp_path, component), backend=desktop)
    assert not desktop.messages and not desktop.menu_commands
    assert desktop.front == 999


@pytest.mark.parametrize('before,after', [('TfrmMain', 'TFrmMain'), ('TFrmMain', 'TfrmMain')])
def test_alias_change_after_observation_still_invalidates_menu_receipt(tmp_path, before, after):
    component = HOSTED_COMPONENTS[0]
    desktop = ComponentDesktop(component, hosted=True)
    desktop.nodes[700]['class'] = before
    observed = module().run_window(request(tmp_path, component), backend=desktop)
    action = action_from_observation(tmp_path, component, observed)
    desktop.nodes[700]['class'] = after
    with pytest.raises(ValueError, match='changed since observation'):
        module().run_window(action, backend=desktop)
    assert not desktop.messages and not desktop.menu_commands
    assert desktop.front == 999


@pytest.mark.parametrize('change', ['host-hash', 'host-root', 'third-pid'])
def test_upper_f_host_alias_keeps_fingerprint_root_and_ancestry_guards(tmp_path, change):
    component = HOSTED_COMPONENTS[0]
    desktop = ComponentDesktop(component, hosted=True)
    desktop.nodes[700]['class'] = 'TFrmMain'
    if change == 'host-hash':
        desktop.identities[77]['sha256'] = '0' * 64
    elif change == 'host-root':
        desktop.identities[77]['executable'] = r'E:\other\GameCenter.exe'
    else:
        desktop.pids[600] = 88
    error, message = ((ValueError, 'ancestor chain') if change == 'third-pid'
                      else (PermissionError, 'verified GameCenter'))
    with pytest.raises(error, match=message):
        module().run_window(request(tmp_path, component), backend=desktop)
    assert not desktop.messages and not desktop.menu_commands
    assert desktop.front == 999
