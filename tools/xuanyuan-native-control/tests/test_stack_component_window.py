"""Requested fixed stack components at reused OS boundaries, never live services."""
import pytest

from test_loginsrv_window import LoginDesktop, request as login_request
from test_native_window import module


COMPONENTS = [
    (r'D:\MirServer\DBServer\DBServer.exe',
     '06DA830E181A7DFDD913A4D322422AD01C755C8A105CA69AE08A7716C25DC6BE', 'GameCenterHostedDBServer'),
    (r'D:\MirServer\RunGate\RunGate.exe',
     'F6494D1A560D9D7D4B2A7BB8EAAEB24D4B38ECE39A84D0630E35E0C3CE23FDC4', 'GameCenterHostedRunGate'),
    (r'D:\MirServer\SelGate\SelGate.exe',
     '4A707773A3AB6CBC93A0C0239B8DCED39EFDD07F31D70DBF50F417EC022E3E55', 'GameCenterHostedSelGate'),
]


@pytest.fixture(params=COMPONENTS, ids=['DBServer', 'RunGate', 'SelGate'])
def component(request):
    return request.param


class ComponentDesktop(LoginDesktop):
    """Reuse real snapshot/hosting/ancestry/messages; add only fake menu Win32 calls."""

    def __init__(self, component, *, hosted=False):
        super().__init__(hosted=hosted)
        executable, digest, _ = component
        self.identities[12].update(executable=executable, sha256=digest)
        self.nodes[345].update({'class': 'TComponentBoundaryFixture', 'text': 'stack boundary fixture'})
        self.menu_commands = []
        self.native.user.GetMenu = lambda hwnd: 1 if hwnd == 345 else 0
        self.native.user.GetMenuItemCount = lambda menu: 1
        self.native.user.GetMenuState = lambda menu, index, flags: 0x100 if menu == 1 else 0
        self.native.user.GetSubMenu = lambda menu, index: 2 if menu == 1 else 0
        self.native.user.GetMenuItemID = lambda menu, index: 42
        self.native.user.GetMenuStringW = self.menu_text

    @staticmethod
    def menu_text(menu, index, buffer, capacity, flags):
        buffer.value = '管理' if menu == 1 else '设置'
        return len(buffer.value)

    def send_message_timeout(self, hwnd, message, wparam, lparam, flags, timeout, result):
        if message == 0x111:
            self.messages.append((hwnd, message, flags, timeout))
            self.menu_commands.append(wparam)
            result._obj.value = 1
            return 1
        return super().send_message_timeout(hwnd, message, wparam, lparam, flags, timeout, result)


def request(tmp_path, component, *, command='window-observe', name='observe'):
    req = login_request(tmp_path, command=command, name=name)
    req['arguments'].update(expectedExecutable=component[0], expectedSha256=component[1],
                            expectedClass='TComponentBoundaryFixture', expectedTitle='stack boundary fixture')
    return req


def action_request(tmp_path, desktop, component, action):
    observed = module().run_window(request(tmp_path, component), backend=desktop)
    req = request(tmp_path, component, command='window-action', name='action')
    req['arguments'].update(observationReceipt=observed['observationReceipt'],
                            observationSha256=observed['observationSha256'], action=action)
    return req


@pytest.mark.parametrize('hosted', [False, True])
def test_requested_component_observation_retains_exact_host_identity_and_chain(tmp_path, component, hosted):
    desktop = ComponentDesktop(component, hosted=hosted)
    result = module().run_window(request(tmp_path, component), backend=desktop)
    target = result['target']
    assert target['executable'] == component[0] and target['sha256'] == component[1]
    if hosted:
        assert target['hosting']['kind'] == component[2]
        assert [(item['hwnd'], item['pid'], item['parent']) for item in target['hosting']['ancestorChain']] == [
            (345, 12, 600), (600, 77, 700), (700, 77, 0)]
    else:
        assert target['hosting'] is None
    assert target['menus'][-1]['path'] == ['管理', '设置']
    assert result['screenshot'] and not desktop.messages
    assert result['recovery'] == {'foregroundRestored': True, 'cursorRestored': True}


@pytest.mark.parametrize('hosted', [False, True])
@pytest.mark.parametrize('kind', ['set-text', 'button', 'menu'])
def test_requested_component_uses_native_set_button_and_menu_contracts(tmp_path, component, hosted, kind):
    desktop = ComponentDesktop(component, hosted=hosted)
    action = ({'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'}
              if kind == 'set-text' else
              {'kind': 'button', 'controlHwnd': 14, 'expectedClass': 'TButton', 'expectedText': '保存'}
              if kind == 'button' else
              {'kind': 'menu', 'path': ['管理', '设置'], 'synchronous': True})
    result = module().run_window(action_request(tmp_path, desktop, component, action), backend=desktop)
    expected = {'set-text': (10, 0xC, 2, 60000), 'button': (14, 0xF5, 2, 60000),
                'menu': (345, 0x111, 2, 60000)}
    assert desktop.messages == [expected[kind]]
    assert desktop.nodes[10]['text'] == ('13' if kind == 'set-text' else '12')
    assert desktop.button_count == (1 if kind == 'button' else 0)
    assert desktop.menu_commands == ([42] if kind == 'menu' else [])
    assert result['actionAttempted'] and result['dispatch']['handlerAcknowledged']
    assert result['readbackVerified'] is (kind == 'set-text')
    assert not result['businessSaveVerified']


def test_old_dbserver_binary_is_not_the_authorized_stack_build(tmp_path):
    component = (COMPONENTS[0][0], '86868707C18D36D044109BF913535F37BB85B40318F04F5510089E4A8A708AE7',
                 'GameCenterHostedDBServer')
    desktop = ComponentDesktop(component, hosted=True)
    with pytest.raises(PermissionError):
        module().run_window(request(tmp_path, component), backend=desktop)
    assert not desktop.messages and desktop.front == 999


@pytest.mark.parametrize('unrequested', [
    (r'D:\MirServer\LoginGate\LoginGate.exe',
     'C410A16962D4E5D556AB0B18AD003D7C769EF7883B5FC2ECEEBA151370707183', 'unused'),
    (r'D:\MirServer\LogServer\LogDataServer.exe',
     'E5F092ECA627B887FB7E3D164A15C9BC7D53F0419AAE865AE0A60B1889DAB330', 'unused'),
])
def test_other_stack_components_are_not_implicitly_enabled(tmp_path, unrequested):
    desktop = ComponentDesktop(unrequested, hosted=True)
    with pytest.raises(PermissionError):
        module().run_window(request(tmp_path, unrequested), backend=desktop)
    assert not desktop.messages and desktop.front == 999


@pytest.mark.parametrize('change', ['host-hash', 'host-root', 'host-class', 'third-pid', 'broken-chain',
                                   'host-hidden', 'host-minimized'])
def test_component_invalid_host_or_ancestry_fails_before_input(tmp_path, component, change):
    desktop = ComponentDesktop(component, hosted=True)
    if change == 'host-hash':
        desktop.identities[77]['sha256'] = '0' * 64
    elif change == 'host-root':
        desktop.identities[77]['executable'] = r'E:\other\GameCenter.exe'
    elif change == 'host-class':
        desktop.nodes[700]['class'] = 'UnknownHost'
    elif change == 'third-pid':
        desktop.pids[600] = 88
    elif change == 'broken-chain':
        desktop.parents[600] = 0
    elif change == 'host-hidden':
        desktop.nodes[700]['visible'] = False
    else:
        desktop.minimized.add(700)
    with pytest.raises((ValueError, PermissionError)):
        module().run_window(request(tmp_path, component), backend=desktop)
    assert not desktop.messages


@pytest.mark.parametrize('change', ['expired', 'target-created', 'host-created', 'parent-class', 'parent-style'])
def test_component_action_rejects_stale_receipt_or_changed_identity(tmp_path, component, change):
    desktop = ComponentDesktop(component, hosted=True)
    req = action_request(tmp_path, desktop, component,
                         {'kind': 'menu', 'path': ['管理', '设置'], 'synchronous': True})
    if change == 'expired':
        desktop.clock += 121
    elif change == 'target-created':
        desktop.identities[12]['processCreated'] = '1338000'
    elif change == 'host-created':
        desktop.identities[77]['processCreated'] = '1338001'
    elif change == 'parent-class':
        desktop.nodes[600]['class'] = 'ChangedPanel'
    else:
        desktop.nodes[600]['style'] ^= 0x10000
    with pytest.raises((ValueError, PermissionError)):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.menu_commands


@pytest.mark.parametrize('kind', ['key', 'visual-click', 'set-text'])
def test_component_input_does_not_cross_into_host_sibling_or_foreign_control(tmp_path, component, kind):
    desktop = ComponentDesktop(component, hosted=True)
    action = ({'kind': 'key', 'key': 'HOME'} if kind == 'key' else
              {'kind': 'visual-click', 'x': 50, 'y': 60} if kind == 'visual-click' else
              {'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit', 'expectedText': '12', 'value': '13'})
    req = action_request(tmp_path, desktop, component, action)
    if kind == 'key':
        desktop.focus = 600
    elif kind == 'visual-click':
        desktop.hit = 800
    else:
        desktop.pids[10] = 77
    with pytest.raises(ValueError):
        module().run_window(req, backend=desktop)
    assert not desktop.messages and not desktop.events


def test_hidden_component_show_cannot_select_the_host_page(tmp_path, component):
    desktop = ComponentDesktop(component, hosted=True)
    desktop.nodes[345]['visible'] = False
    req = action_request(tmp_path, desktop, component, {'kind': 'show'})
    with pytest.raises(ValueError, match='host page'):
        module().run_window(req, backend=desktop)
    assert not desktop.messages


def test_component_cannot_claim_another_components_host_adapter(component):
    desktop = ComponentDesktop(component, hosted=True)
    target = desktop.snapshot(12, 345)
    assert target['hosting'] is not None, 'Requested component needs its verified GameCenter adapter'
    target['hosting']['kind'] = 'GameCenterHostedLoginSrv'
    with pytest.raises(PermissionError):
        module()._check_hosting(target)
