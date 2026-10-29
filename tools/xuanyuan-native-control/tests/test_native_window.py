"""OS-boundary fixtures exercise native window contracts without GUI input."""
import copy
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
EXE = r'D:\Mirserver100\Mir200\M2Server.exe'
HASH = '1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A'


def module():
    assert importlib.util.find_spec('wzl_blackbox.native_window'), 'native window adapter is not implemented'
    from wzl_blackbox import native_window
    return native_window


class Desktop:
    def __init__(self):
        self.clock = time.time()
        self.front, self.pointer = 999, [3, 4]
        self.target = {'pid': 12, 'hwnd': 345, 'parent':0, 'owner':0, 'style':0, 'hosting':None, 'class': 'TfrmMonster', 'title': '自定义怪物',
                       'executable': EXE, 'sha256': HASH, 'processCreated': '13370001',
                       'rect': [10, 20, 810, 620], 'clientSize': [780, 560], 'clientOrigin': [20, 50],
                       'visible': True, 'enabled': True, 'minimized': False, 'blockingWindows': [],
                       'controls': [self.control(10, 'TEdit', '12'),
                                    dict(self.control(11, 'TComboBox', 'one'), options=['one', 'two'], selectedIndex=0),
                                    dict(self.control(12, 'TPageControl', ''), tabs=['基本', '动作'], selectedIndex=0, selectedText='基本'),
                                    dict(self.control(13, 'TCheckBox', '启用'), check=0),
                                    self.control(14, 'TButton', '保存')],
                       'menus': [{'path': ['选项', '怪物设置', '自定义怪物'], 'id': 42, 'enabled': True}]}
        self.forms = [{'hwnd': 345, 'class': 'TfrmMonster', 'title': '自定义怪物', 'visible': True, 'enabled': True},
                      {'hwnd': 346, 'class': 'TfrmMain', 'title': 'M2', 'visible': True, 'enabled': False}]
        self.events, self.held = [], set()
        self.closed = False
        self.fail_down = False
        self.covered = False
        self.restore_ok = True

    def control(self, hwnd, cls, text):
        return {'hwnd': hwnd, 'parent': 345, 'owner':0, 'style':0, 'class': cls, 'text': text,
                'rect': [30, 60, 100, 85], 'visible': True, 'enabled': True}

    def now(self): return self.clock
    def foreground(self): return self.front
    def cursor(self): return self.pointer[:]
    def sleep(self, seconds): pass
    def assert_input_idle(self):
        if self.held: raise ValueError('held input')
    def snapshot(self, pid, hwnd):
        if self.closed: raise ValueError('window no longer exists')
        return copy.deepcopy(self.target)
    def native_forms(self, pid):
        return [] if self.closed else copy.deepcopy(self.forms)
    def exists(self, hwnd): return not self.closed if hwnd == 345 else hwnd == 999
    def activate(self, hwnd): self.front = hwnd
    def restore(self, front, pointer):
        if self.restore_ok and self.exists(front): self.front, self.pointer = front, pointer[:]
        return {'foregroundRestored': self.exists(front) and self.front == front, 'cursorRestored': self.pointer == pointer}
    def client_to_screen(self, hwnd, x, y): return [20+x, 50+y]
    def root_at(self, point): return 888 if self.covered else 345
    def root(self, hwnd): return hwnd
    def point_in_form(self, hwnd, point): return not self.covered
    def observation_point_in_form(self, hwnd, point): return not self.covered
    def focus_in_form(self, hwnd): return True
    def control_in_form(self, control, hwnd): return True
    def move(self, point): self.pointer = point[:]
    def screenshot(self, path, rect): Path(path).write_bytes(b'captured pixels')
    def down(self, kind, value):
        self.held.add((kind, value)); self.events.append(('down', kind, value))
        if self.fail_down: raise RuntimeError('send failed')
    def up(self, kind, value):
        self.held.discard((kind, value)); self.events.append(('up', kind, value))
    def dispatch(self, target, action):
        self.events.append(('dispatch', copy.deepcopy(action)))
        kind = action['kind']
        control = next((x for x in self.target['controls'] if x['hwnd'] == action.get('controlHwnd')), None)
        if kind == 'set-text': control['text'] = action['value']
        elif kind == 'select-combo': control.update(selectedIndex=action['index'], text=control['options'][action['index']])
        elif kind == 'select-tab':
            control.update(selectedIndex=control['tabs'].index(action['text']), selectedText=action['text'])
        elif kind == 'button' and control['class'] == 'TCheckBox': control['check'] = 1-control['check']
        elif kind == 'show':
            if self.target['minimized']:
                self.target.update(clientSize=[780,560],rect=[10,20,810,620])
            self.target.update(visible=True, minimized=False); self.front=self.target['hwnd']
        elif kind == 'close': self.closed = True
        return {'acknowledged': True, 'message': kind}


def request(tmp_path, command='window-observe', name='observe'):
    return {'schemaVersion': 1, 'command': command,
            'arguments': {'pid': 12, 'hwnd': 345, 'expectedExecutable': EXE, 'expectedSha256': HASH,
                          'expectedClass': 'TfrmMonster', 'expectedTitle': '自定义怪物', 'outputRoot': str(tmp_path/name)},
            'policy': {'allowedWriteRoots': [str(tmp_path)]}}


def action_request(tmp_path, desktop, action):
    data = module().run_window(request(tmp_path), backend=desktop)
    receipt = Path(data['outputRoot'])/'observation.json'
    req = request(tmp_path, 'window-action', 'action')
    req['arguments'].update(observationReceipt=str(receipt), observationSha256=hashlib.sha256(receipt.read_bytes()).hexdigest(), action=action)
    return req


def test_observation_contains_controls_native_forms_menu_and_recovered_pixels(tmp_path):
    d = Desktop(); data = module().run_window(request(tmp_path), backend=d)
    assert data['target']['controls'][1]['options'] == ['one', 'two']
    assert data['forms'][1]['enabled'] is False
    assert data['target']['menus'][0]['path'] == ['选项', '怪物设置', '自定义怪物']
    assert data['recovery'] == {'foregroundRestored': True, 'cursorRestored': True}
    receipt=Path(data['observationReceipt'])
    assert json.loads(receipt.read_text('utf-8')) == {k:v for k,v in data.items() if k not in ('observationReceipt','observationSha256')}
    assert hashlib.sha256(receipt.read_bytes()).hexdigest().upper() == data['observationSha256']
    assert d.front == 999 and d.events == []


@pytest.mark.parametrize('field,value', [('expectedExecutable', r'D:\unknown.exe'), ('expectedSha256', '0'*64), ('pid', True), ('hwnd', 0)])
def test_invalid_explicit_identity_rejected_before_input(tmp_path, field, value):
    d=Desktop(); req=request(tmp_path); req['arguments'][field]=value
    with pytest.raises((ValueError, PermissionError)): module().run_window(req, backend=d)
    assert not d.events and d.front == 999


def test_identical_verified_executable_in_formal_root_is_accepted(tmp_path):
    d=Desktop(); d.target['executable']=r'D:\MirServer\Mir200\M2Server.exe'
    req=request(tmp_path); req['arguments']['expectedExecutable']=d.target['executable']
    assert module().run_window(req, backend=d)['target']['executable'] == d.target['executable']


def test_hidden_observation_has_no_pixels_and_only_show_can_use_it(tmp_path):
    d=Desktop(); d.target['visible']=False
    req=action_request(tmp_path,d,{'kind':'show'})
    assert json.loads(Path(req['arguments']['observationReceipt']).read_text('utf-8'))['screenshot'] is None
    data=module().run_window(req,backend=d)
    assert data['target']['visible'] and data['screenshot']


@pytest.mark.parametrize('action', [{'kind':'set-text','controlHwnd':10,'expectedClass':'TEdit','expectedText':'12','value':'33'},
                                    {'kind':'select-combo','controlHwnd':11,'expectedClass':'TComboBox','expectedIndex':0,'expectedOptions':['one','two'],'index':1},
                                    {'kind':'select-tab','controlHwnd':12,'expectedClass':'TPageControl','expectedSelection':'基本','text':'动作'},
                                    {'kind':'button','controlHwnd':13,'expectedClass':'TCheckBox','expectedText':'启用','expectedCheck':0},
                                    {'kind':'menu','path':['选项','怪物设置','自定义怪物']}])
def test_one_native_action_dispatches_once_and_returns_control_readback(tmp_path,action):
    d=Desktop(); req=action_request(tmp_path,d,action)
    data=module().run_window(req,backend=d)
    assert len(d.events) == 1 and data['actionAttempted'] and data['dispatch']['acknowledged']
    if action['kind']=='set-text': assert data['target']['controls'][0]['text']=='33'
    elif action['kind']=='select-combo': assert data['target']['controls'][1]['selectedIndex']==1
    elif action['kind']=='select-tab': assert data['target']['controls'][2]['selectedText']=='动作'
    elif action['kind']=='button': assert data['target']['controls'][3]['check']==1


@pytest.mark.parametrize('field,value', [('processCreated','changed'),('rect',[0,0,800,600]),('visible',False),('enabled',False),('title','another'),('sha256','0'*64)])
def test_changed_live_window_rejects_receipt_without_dispatch(tmp_path,field,value):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'}); d.target[field]=value
    with pytest.raises((ValueError, PermissionError)): module().run_window(req,backend=d)
    assert not d.events


def test_receipt_freshness_and_image_fingerprint_are_checked(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'}); d.clock+=121
    with pytest.raises(ValueError,match='120'): module().run_window(req,backend=d)
    assert not d.events


@pytest.mark.parametrize('change', ['text','class','hidden','disabled','combo-options','tab-selection','check','missing','menu'])
def test_changed_control_and_menu_preconditions_rejected(tmp_path,change):
    d=Desktop(); action={'kind':'set-text','controlHwnd':10,'expectedClass':'TEdit','expectedText':'12','value':'33'}
    if change=='combo-options': action={'kind':'select-combo','controlHwnd':11,'expectedClass':'TComboBox','expectedIndex':0,'expectedOptions':['one','two'],'index':1}
    if change=='tab-selection': action={'kind':'select-tab','controlHwnd':12,'expectedClass':'TPageControl','expectedSelection':'基本','text':'动作'}
    if change=='check': action={'kind':'button','controlHwnd':13,'expectedClass':'TCheckBox','expectedText':'启用','expectedCheck':0}
    if change=='menu': action={'kind':'menu','path':['选项','怪物设置','自定义怪物']}
    req=action_request(tmp_path,d,action)
    if change=='text': d.target['controls'][0]['text']='99'
    elif change=='class': d.target['controls'][0]['class']='TButton'
    elif change=='hidden': d.target['controls'][0]['visible']=False
    elif change=='disabled': d.target['controls'][0]['enabled']=False
    elif change=='combo-options': d.target['controls'][1]['options']=['new']
    elif change=='tab-selection': d.target['controls'][2]['selectedText']='动作'
    elif change=='check': d.target['controls'][3]['check']=1
    elif change=='missing': d.target['controls']=[]
    elif change=='menu': d.target['menus'][0]['enabled']=False
    with pytest.raises(ValueError): module().run_window(req,backend=d)
    assert not d.events


def test_visible_enabled_modal_can_operate_with_disabled_main(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'END'})
    assert module().run_window(req,backend=d)['actionAttempted']
    assert not d.held


def test_target_blocked_by_owned_modal_rejects_input(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'}); d.target['blockingWindows']=[{'hwnd':400}]
    with pytest.raises(ValueError,match='modal'): module().run_window(req,backend=d)
    assert not d.events


def test_single_visual_input_releases_even_if_press_raises(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'visual-click','x':50,'y':60,'button':'right'}); d.fail_down=True
    with pytest.raises(RuntimeError,match='send failed'): module().run_window(req,backend=d)
    assert d.events == [('down','mouse','right'),('up','mouse','right')] and not d.held
    failure=json.loads((tmp_path/'action'/'failure.json').read_text('utf-8'))
    assert failure['actionAttempted'] and failure['recovery']['foregroundRestored']


def test_closed_target_is_not_resnapshotted_and_new_forms_returned(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'close'})
    data=module().run_window(req,backend=d)
    assert data['target'] is None and data['forms']==[] and data['targetClosed']


def test_closed_original_foreground_is_not_claimed_restored(tmp_path):
    d=Desktop(); d.front=345; req=action_request(tmp_path,d,{'kind':'close'})
    with pytest.raises(RuntimeError,match='restore'): module().run_window(req,backend=d)
    failure=json.loads((tmp_path/'action'/'failure.json').read_text('utf-8'))
    assert failure['recovery']['foregroundRestored'] is False


@pytest.mark.parametrize('action', [{'kind':'set-text','controlHwnd':10,'expectedClass':'TEdit','expectedText':'12','value':'33'},
                                    {'kind':'select-combo','controlHwnd':11,'expectedClass':'TComboBox','expectedIndex':0,'expectedOptions':['one','two'],'index':1},
                                    {'kind':'select-tab','controlHwnd':12,'expectedClass':'TPageControl','expectedSelection':'基本','text':'动作'}])
def test_message_ack_without_desired_control_readback_is_failure(tmp_path,action):
    d=Desktop(); req=action_request(tmp_path,d,action)
    def ignored(target,action):
        d.events.append(('ignored',action)); return {'acknowledged':True}
    d.dispatch=ignored
    with pytest.raises(ValueError,match='readback'): module().run_window(req,backend=d)
    assert json.loads((tmp_path/'action'/'failure.json').read_text('utf-8'))['actionAttempted']


def test_modal_appearing_during_activation_rejects_before_dispatch(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'button','controlHwnd':14,'expectedClass':'TButton','expectedText':'保存'})
    original=d.activate
    def activate(hwnd):
        original(hwnd); d.target['blockingWindows']=[{'hwnd':444}]
    d.activate=activate
    with pytest.raises(ValueError,match='modal'): module().run_window(req,backend=d)
    assert not d.events


def test_truncated_edit_value_cannot_be_overwritten_as_if_complete(tmp_path):
    d=Desktop(); d.target['controls'][0]['textTruncated']=True
    req=action_request(tmp_path,d,{'kind':'set-text','controlHwnd':10,'expectedClass':'TEdit','expectedText':'12','value':'33'})
    with pytest.raises(ValueError,match='truncated'): module().run_window(req,backend=d)
    assert not d.events


def test_timed_out_native_handler_records_unknown_state_and_new_forms(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'menu','path':['选项','怪物设置','自定义怪物'],'synchronous':True})
    def timeout(target,action):
        d.forms.append({'hwnd':400,'class':'TMessageForm','title':'确认','visible':True,'enabled':True})
        raise TimeoutError('no handler ACK')
    d.dispatch=timeout
    with pytest.raises(TimeoutError): module().run_window(req,backend=d)
    result=json.loads((tmp_path/'action'/'failure.json').read_text('utf-8'))
    assert result['actionAttempted'] and result['forms'][-1]['title']=='确认'


def test_long_native_log_is_observable_with_explicit_truncation():
    import ctypes
    m=module(); backend=object.__new__(m.Win32WindowBackend)
    calls=[]
    def message(hwnd,msg,wparam=0,lparam=0,timeout=2000):
        calls.append((msg,wparam))
        if msg==0xE: return 90000
        ctypes.memmove(lparam, ctypes.create_unicode_buffer('bounded log'), 24)
        return 11
    backend._message=message
    text,truncated=backend._title(123)
    assert text=='bounded log' and truncated and calls[-1][1] == 65536


@pytest.mark.parametrize('field', ['owner','parent'])
def test_window_owner_and_parent_changes_invalidate_observation(tmp_path,field):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'}); d.target[field]=777
    with pytest.raises(ValueError): module().run_window(req,backend=d)
    assert not d.events


def test_recovery_errors_cannot_be_promoted_to_valid_observation(tmp_path):
    d=Desktop()
    original=d.restore
    def restore(front,pointer):
        return dict(original(front,pointer),errors=['Could not detach foreground input queues'])
    d.restore=restore
    with pytest.raises(RuntimeError,match='restore'): module().run_window(request(tmp_path),backend=d)
    assert not (tmp_path/'observe'/'observation.json').exists()


def test_receipt_with_recovery_error_is_not_consumable(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'}); receipt=Path(req['arguments']['observationReceipt'])
    data=json.loads(receipt.read_text('utf-8')); data['recovery']['errors']=['detach failed']
    receipt.write_text(json.dumps(data),encoding='utf-8'); req['arguments']['observationSha256']=hashlib.sha256(receipt.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='recovered'): module().run_window(req,backend=d)
    assert not d.events


def test_menu_and_close_default_to_one_post_and_explicit_sync_has_ack():
    from types import SimpleNamespace
    m=module(); backend=object.__new__(m.Win32WindowBackend); calls=[]
    backend.user=SimpleNamespace(PostMessageW=lambda *args: calls.append(('post',args)) or 1)
    backend._message=lambda *args,**kwargs: calls.append(('send',args,kwargs)) or 0
    target={'hwnd':345,'menus':[{'path':['选项','测试'],'id':42}]}
    result=backend.dispatch(target,m._action({'kind':'menu','path':['选项','测试']}))
    assert result['mode']=='posted' and not result['handlerAcknowledged'] and calls==[('post',(345,0x111,42,0))]
    calls.clear(); result=backend.dispatch(target,m._action({'kind':'close'}))
    assert result['mode']=='posted' and calls==[('post',(345,0x10,0,0))]
    calls.clear(); result=backend.dispatch(target,m._action({'kind':'menu','path':['选项','测试'],'synchronous':True}))
    assert result['handlerAcknowledged'] and calls==[('send',(345,0x111,42,0),{'timeout':60000})]


def test_foreground_changed_after_action_cannot_produce_consumable_pixels(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    d.sleep=lambda seconds: setattr(d,'front',888)
    with pytest.raises(ValueError,match='focus'): module().run_window(req,backend=d)
    assert not (tmp_path/'action'/'observation.json').exists()


def test_geometry_changed_during_capture_cannot_produce_consumable_pixels(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    original=d.screenshot
    def screenshot(path,rect):
        original(path,rect); d.target['rect']=[11,20,811,620]
    d.screenshot=screenshot
    with pytest.raises(ValueError,match='capture'): module().run_window(req,backend=d)
    assert not (tmp_path/'action'/'observation.json').exists()


@pytest.mark.parametrize('field,value',[('parent',888),('owner',777),('rect',[60,60,140,85])])
def test_control_reparenting_or_relayout_invalidates_receipt(tmp_path,field,value):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'set-text','controlHwnd':10,'expectedClass':'TEdit','expectedText':'12','value':'33'})
    d.target['controls'][0][field]=value
    with pytest.raises(ValueError,match='Control'): module().run_window(req,backend=d)
    assert not d.events


def test_keyboard_interrupt_preserves_failure_attempt_and_restores_desktop(tmp_path):
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    def interrupted(seconds): raise KeyboardInterrupt('operator interrupt')
    d.sleep=interrupted
    with pytest.raises(KeyboardInterrupt,match='operator interrupt'): module().run_window(req,backend=d)
    result=json.loads((tmp_path/'action'/'failure.json').read_text('utf-8'))
    assert result['actionAttempted'] and result['recovery']['foregroundRestored'] and not d.held


def test_multiline_edit_uses_native_replace_sequence_that_notifies_host():
    m=module(); backend=object.__new__(m.Win32WindowBackend); calls=[]
    backend._message=lambda *args,**kwargs: calls.append((args[:3],kwargs)) or 1
    target={'hwnd':345,'controls':[{'hwnd':10,'class':'TMemo','style':4}]}
    result=backend.dispatch(target,{'kind':'set-text','controlHwnd':10,'value':'new line'})
    assert [args for args,kwargs in calls]==[(10,0xB1,0),(10,0xC2,1)]
    assert result['handlerAcknowledged']


def test_button_style_tab_is_rejected_before_unproven_selection(tmp_path):
    d=Desktop(); d.target['controls'][2]['style']=0x100
    req=action_request(tmp_path,d,{'kind':'select-tab','controlHwnd':12,'expectedClass':'TPageControl','expectedSelection':'基本','text':'动作'})
    with pytest.raises(ValueError,match='button-style'): module().run_window(req,backend=d)
    assert not d.events


def test_child_form_cannot_use_ancestor_root_as_proof_of_input_focus(tmp_path):
    d=Desktop(); d.root=lambda hwnd:346 if hwnd==345 else hwnd; d.root_at=lambda point:346
    req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    with pytest.raises(ValueError,match='Child native form'): module().run_window(req,backend=d)
    assert not d.events


def test_native_root_preserves_real_cross_process_gamecenter_host():
    from types import SimpleNamespace
    m=module(); backend=object.__new__(m.Win32WindowBackend)
    backend.user=SimpleNamespace(GetAncestor=lambda hwnd,flag:134250, GetParent=lambda hwnd:0)
    backend.window_long=lambda hwnd,index:0x36CF0000
    assert backend.root(56564676)==134250


def test_native_point_root_preserves_real_cross_process_gamecenter_host():
    from types import SimpleNamespace
    from ctypes import wintypes
    m=module(); backend=object.__new__(m.Win32WindowBackend); backend.w=wintypes
    parents={10:20,20:345}; styles={10:0x50000000,20:0x50000000,345:0x36CF0000}
    backend.user=SimpleNamespace(WindowFromPoint=lambda point:10,GetAncestor=lambda hwnd,flag:134250,
                                 GetParent=lambda hwnd:parents.get(hwnd,0))
    backend.window_long=lambda hwnd,index:styles[hwnd]
    assert backend.root(10)==134250 and backend.root_at([50,60])==134250


def hosted_desktop():
    d=Desktop()
    d.target['hosting']={'kind':'GameCenterHostedM2','rootHwnd':700,'pid':77,'class':'TfrmMain','title':'翎风引擎控制台',
                         'executable':r'D:\Mirserver100\GameCenter.exe',
                         'sha256':'497C03D8C323258069EB4582F1C291BA5C67E190D8C31DDC5FAD5A79C2D72857',
                         'processCreated':'1337999','visible':True,'enabled':True,'minimized':False,
                         'ancestorChain':[{'hwnd':345,'pid':12,'parent':600,'class':'TfrmMonster','style':0,'rect':[10,20,810,620],'visible':True,'enabled':True},
                                          {'hwnd':600,'pid':77,'parent':700,'class':'TPanel','style':0x50000000,'rect':[0,0,900,700],'visible':True,'enabled':True},
                                          {'hwnd':700,'pid':77,'parent':0,'class':'TfrmMain','style':0x16CB0000,'rect':[0,0,900,700],'visible':True,'enabled':True}]}
    d.root=lambda hwnd:700 if hwnd==345 else hwnd
    d.root_at=lambda point:888 if d.covered else 700
    return d


def test_verified_gamecenter_hosted_m2_uses_host_foreground_and_target_point_membership(tmp_path):
    d=hosted_desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    result=module().run_window(req,backend=d)
    assert result['actionAttempted'] and d.front==999 and not d.held


@pytest.mark.parametrize('field,value',[('sha256','0'*64),('executable',r'E:\other\GameCenter.exe'),('class','UnknownHost')])
def test_unverified_or_different_engine_host_is_rejected_without_input(tmp_path,field,value):
    d=hosted_desktop(); d.target['hosting'][field]=value
    with pytest.raises((ValueError,PermissionError)): module().run_window(request(tmp_path),backend=d)
    assert not d.events and d.front==999


@pytest.mark.parametrize('field,value',[('processCreated','1337000'),('pid',88),('rootHwnd',701)])
def test_changed_host_identity_invalidates_prior_m2_observation(tmp_path,field,value):
    d=hosted_desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'}); d.target['hosting'][field]=value
    with pytest.raises((ValueError,PermissionError)): module().run_window(req,backend=d)
    assert not d.events


def test_host_toolbar_point_with_same_ga_root_cannot_control_embedded_m2(tmp_path):
    d=hosted_desktop(); req=action_request(tmp_path,d,{'kind':'visual-click','x':50,'y':60})
    d.point_in_form=lambda hwnd,point:False
    with pytest.raises(ValueError,match='form'): module().run_window(req,backend=d)
    assert not d.events


def test_navigation_key_with_focus_in_host_or_sibling_is_rejected(tmp_path):
    d=hosted_desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    d.focus_in_form=lambda hwnd:False
    with pytest.raises(ValueError,match='focus'): module().run_window(req,backend=d)
    assert not d.events


def test_hidden_hosted_m2_requires_selecting_host_page_before_show(tmp_path):
    d=hosted_desktop(); d.target['visible']=False
    req=action_request(tmp_path,d,{'kind':'show'})
    with pytest.raises(ValueError,match='host page'): module().run_window(req,backend=d)
    assert not d.events


@pytest.mark.parametrize('bits,size,offsets',[(32,28,(12,16,24)),(64,40,(16,24,32))])
def test_tab_item_remote_abi_matches_target_process_bitness(bits,size,offsets):
    import ctypes
    item=module()._tab_item_type(bits)
    assert ctypes.sizeof(item)==size
    assert (item.pszText.offset,item.cchTextMax.offset,item.lParam.offset)==offsets


@pytest.mark.parametrize('bits,unicode_window,message',[(32,False,0x1305),(64,True,0x133C)])
def test_bounded_tab_reads_use_target_abi_and_string_encoding(monkeypatch,bits,unicode_window,message):
    import ctypes
    from types import SimpleNamespace
    import pywinauto.remote_memory_block as remote_module
    m=module(); backend=object.__new__(m.Win32WindowBackend)
    def process(hwnd,pointer): pointer._obj.value=77; return 1
    backend.w=SimpleNamespace(DWORD=ctypes.c_uint32)
    backend.user=SimpleNamespace(GetWindowThreadProcessId=process,IsWindowUnicode=lambda hwnd:unicode_window)
    backend._pointer_bits=lambda pid:bits
    state={'index':0,'closed':False,'messages':[]}
    class Memory:
        def __init__(self,ctrl,size=4096): assert ctrl.handle==123
        def Address(self): return 0x10000
        def Write(self,data,address=None,size=None):
            if address is None:
                assert ctypes.sizeof(data)==(28 if bits==32 else 40)
                assert data.pszText==0x10000+ctypes.sizeof(data)
        def Read(self,buffer,address=None):
            value=['控制台','M2'][state['index']]
            raw=value.encode('utf-16-le')+b'\0\0' if unicode_window else value.encode('mbcs')+b'\0'
            ctypes.memmove(ctypes.addressof(buffer),raw,len(raw)); return buffer
        def CleanUp(self): state['closed']=True
    monkeypatch.setattr(remote_module,'RemoteMemoryBlock',Memory)
    def send(hwnd,msg,wparam=0,lparam=0,timeout=2000):
        state['messages'].append(msg)
        if msg==0x1304: return 2
        assert msg==message and lparam==0x10000
        state['index']=wparam; return 1
    backend._message=send
    assert backend._read_tabs(123)==['控制台','M2']
    assert state['closed'] and state['messages']==[0x1304,message,message]


@pytest.mark.parametrize('exception_type',[TimeoutError,KeyboardInterrupt,SystemExit])
def test_timed_out_remote_tab_buffer_is_retained_until_target_exit(monkeypatch,exception_type):
    import ctypes
    from types import SimpleNamespace
    import pywinauto.remote_memory_block as remote_module
    m=module(); backend=object.__new__(m.Win32WindowBackend)
    def process(hwnd,pointer): pointer._obj.value=77; return 1
    backend.w=SimpleNamespace(DWORD=ctypes.c_uint32)
    backend.user=SimpleNamespace(GetWindowThreadProcessId=process,IsWindowUnicode=lambda hwnd:False)
    backend._pointer_bits=lambda pid:32
    state={'freed':False,'handleClosed':False}
    class Memory:
        def __init__(self,ctrl,size=4096): self.mem_address=0x10000
        def Address(self): return self.mem_address
        def Write(self,*args): pass
        def Read(self,*args): raise AssertionError('No reads without ACK')
        def CleanUp(self): state['freed']=True
        def _CloseHandle(self): state['handleClosed']=True
    monkeypatch.setattr(remote_module,'RemoteMemoryBlock',Memory)
    def send(hwnd,msg,*args):
        if msg==0x1304: return 1
        raise exception_type('no ACK')
    backend._message=send
    with pytest.raises(exception_type) as error: backend._read_tabs(123)
    assert state=={'freed':False,'handleClosed':True}
    assert error.value.retainedRemoteBuffer=={'pid':77,'address':65536,'bytes':4096,'reason':'handler ACK missing'}


def test_control_callback_keeps_interrupt_inside_python_until_after_win32_enumeration():
    import ctypes
    from types import SimpleNamespace
    m=module(); backend=object.__new__(m.Win32WindowBackend); state={'leaked':False}
    backend.w=SimpleNamespace(DWORD=ctypes.c_uint32)
    backend.enum_callback=lambda fn:fn
    def process(hwnd,pointer): pointer._obj.value=77; return 1
    def enumerate_children(hwnd,callback,unused):
        try: return callback(10,0)
        except BaseException: state['leaked']=True; return True
    backend.user=SimpleNamespace(GetWindowThreadProcessId=process,EnumChildWindows=enumerate_children)
    backend._basic=lambda hwnd:{'hwnd':10,'class':'TPageControl','visible':True}
    def interrupt(hwnd): raise KeyboardInterrupt('tab interrupt')
    backend._read_tabs=interrupt
    with pytest.raises(KeyboardInterrupt,match='tab interrupt'): backend._controls(345)
    assert not state['leaked']


def test_host_point_or_focus_cannot_cross_into_embedded_foreign_process():
    import ctypes
    from types import SimpleNamespace
    m=module(); backend=object.__new__(m.Win32WindowBackend)
    parents={10:345,345:600,600:700}; pids={10:12,345:12,600:77,700:77}
    backend.w=SimpleNamespace(DWORD=ctypes.c_uint32)
    def process(hwnd,pointer): pointer._obj.value=pids[hwnd]; return 1
    backend.user=SimpleNamespace(GetAncestor=lambda hwnd,flag:parents.get(hwnd,0),GetWindowThreadProcessId=process)
    assert backend._inside(10,345)
    assert not backend._inside(10,700)


def test_observing_host_allows_embedded_pixels_but_semantic_controls_need_actual_pid_chain(tmp_path):
    d=Desktop(); d.point_in_form=lambda hwnd,point:False
    data=module().run_window(request(tmp_path),backend=d)
    assert data['screenshot'] and not d.events
    receipt=Path(data['observationReceipt'])
    req=request(tmp_path,'window-action','action')
    req['arguments'].update(observationReceipt=str(receipt),observationSha256=data['observationSha256'],
                            action={'kind':'button','controlHwnd':14,'expectedClass':'TButton','expectedText':'保存'})
    d.control_in_form=lambda control,hwnd:False
    with pytest.raises(ValueError,match='Control'): module().run_window(req,backend=d)
    assert not d.events


def test_semantic_host_control_is_allowed_when_window_center_shows_embedded_content(tmp_path):
    d=Desktop(); d.point_in_form=lambda hwnd,point:False
    req=action_request(tmp_path,d,{'kind':'select-tab','controlHwnd':12,'expectedClass':'TPageControl','expectedSelection':'基本','text':'动作'})
    result=module().run_window(req,backend=d)
    assert result['readbackVerified'] and len(d.events)==1


@pytest.mark.parametrize('stage',['observe','dispatch','capture'])
def test_hosted_m2_same_root_sibling_pixels_cannot_become_bound_observation(tmp_path,stage):
    d=hosted_desktop()
    if stage=='observe':
        d.observation_point_in_form=lambda hwnd,point:False
        req=request(tmp_path)
    else:
        req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
        if stage=='dispatch':
            original=d.activate
            def activate(hwnd):
                original(hwnd); d.observation_point_in_form=lambda hwnd,point:False
            d.activate=activate
        else:
            d.sleep=lambda seconds:setattr(d,'observation_point_in_form',lambda hwnd,point:False)
    with pytest.raises(ValueError,match='ancestor'): module().run_window(req,backend=d)
    if stage!='capture': assert not d.events
    assert not (Path(req['arguments']['outputRoot'])/'observation.json').exists()


def test_observation_ancestry_can_include_embedded_process_while_input_ancestry_cannot():
    import ctypes
    from types import SimpleNamespace
    m=module(); backend=object.__new__(m.Win32WindowBackend)
    parents={10:345,345:600,600:700}; pids={10:12,345:12,600:77,700:77}
    backend.w=SimpleNamespace(DWORD=ctypes.c_uint32)
    def process(hwnd,pointer): pointer._obj.value=pids[hwnd]; return 1
    backend.user=SimpleNamespace(GetAncestor=lambda hwnd,flag:parents.get(hwnd,0),GetWindowThreadProcessId=process)
    assert backend._inside(10,700,same_process=False)
    assert not backend._inside(10,700)
    assert not backend._inside(600,345,same_process=False)


@pytest.mark.parametrize('old_style,new_style',[(0x50030001,0x50030000),(0x50030000,0x50030001)])
def test_pushbutton_default_focus_style_transition_keeps_same_control_identity(tmp_path,old_style,new_style):
    d=Desktop(); d.target['controls'][4].update({'class':'Button','style':old_style})
    req=action_request(tmp_path,d,{'kind':'button','controlHwnd':14,'expectedClass':'Button','expectedText':'保存'})
    d.target['controls'][4]['style']=new_style
    result=module().run_window(req,backend=d)
    assert result['actionAttempted'] and len(d.events)==1


@pytest.mark.parametrize('new_style',[0x50030002,0x58030000,0x50020000,0x50030008])
def test_pushbutton_other_types_and_window_style_changes_still_invalidate_receipt(tmp_path,new_style):
    d=Desktop(); d.target['controls'][4].update({'class':'Button','style':0x50030001})
    req=action_request(tmp_path,d,{'kind':'button','controlHwnd':14,'expectedClass':'Button','expectedText':'保存'})
    d.target['controls'][4]['style']=new_style
    with pytest.raises(ValueError,match='Control'): module().run_window(req,backend=d)
    assert not d.events


def test_checkbox_cannot_borrow_pushbutton_default_style_equivalence(tmp_path):
    d=Desktop(); d.target['controls'][3]['style']=0x50030000
    req=action_request(tmp_path,d,{'kind':'button','controlHwnd':13,'expectedClass':'TCheckBox','expectedText':'启用','expectedCheck':0})
    d.target['controls'][3]['style']=0x50030001
    with pytest.raises(ValueError,match='Control'): module().run_window(req,backend=d)
    assert not d.events


def test_native_activation_initializes_message_queue_before_shared_foreground_attachment(monkeypatch):
    from ctypes import wintypes
    from types import SimpleNamespace
    m=module(); backend=object.__new__(m.Win32WindowBackend); backend.w=wintypes
    state={'queueReady':False,'activated':None}
    def peek(message,hwnd,low,high,flags):
        assert hwnd is None and (low,high,flags)==(0,0,0)
        state['queueReady']=True
        return 0  # Empty queue is a successful initialization.
    backend.user=SimpleNamespace(PeekMessageW=peek)
    def activate(self,hwnd):
        assert state['queueReady'], 'AttachThreadInput requires a current-thread message queue'
        state['activated']=hwnd
    monkeypatch.setattr(m.Win32GameBackend,'activate',activate)
    backend.activate(1381452)
    assert state=={'queueReady':True,'activated':1381452}


def test_minimized_visible_native_form_with_zero_client_size_is_observable_and_restorable(tmp_path):
    d=Desktop(); d.target.update(minimized=True,clientSize=[0,0])
    req=action_request(tmp_path,d,{'kind':'show'})
    observation=json.loads(Path(req['arguments']['observationReceipt']).read_text('utf-8'))
    assert observation['target']['minimized'] and observation['screenshot'] is None
    result=module().run_window(req,backend=d)
    assert result['actionAttempted'] and not result['target']['minimized'] and result['screenshot']


@pytest.mark.parametrize('action',[{'kind':'key','key':'HOME'},
                                    {'kind':'button','controlHwnd':14,'expectedClass':'TButton','expectedText':'保存'}])
def test_minimized_native_receipt_cannot_authorize_other_inputs(tmp_path,action):
    d=Desktop(); d.target.update(minimized=True,clientSize=[0,0])
    req=action_request(tmp_path,d,action)
    with pytest.raises(ValueError): module().run_window(req,backend=d)
    assert not d.events and d.front==999


@pytest.mark.parametrize('child_count',[7,8,9,15,16,24])
@pytest.mark.parametrize('disabled',[False,True])
def test_submenu_count_high_byte_is_not_a_separator_and_real_separator_is_omitted(child_count,disabled):
    from types import SimpleNamespace
    m=module(); backend=object.__new__(m.Win32WindowBackend)
    menus={1:[{'text':'管理(&M)','state':(child_count<<8)|(1 if disabled else 0),'submenu':2},
              {'text':'','state':0x800,'id':0},
              {'text':'控制(&C)','state':1<<8,'submenu':3}],
           2:[{'text':f'管理项{i}','state':0,'id':100+i} for i in range(child_count)],
           3:[{'text':'重新加载(&R)','state':8<<8,'submenu':4}],
           4:[{'text':'怪物数据库(&M)' if i==0 else f'重读项{i}','state':0,'id':900+i} for i in range(8)]}
    def text(menu,index,buffer,length,flags):
        assert flags==0x400
        buffer.value=menus[menu][index]['text']; return len(buffer.value)
    backend.user=SimpleNamespace(GetMenu=lambda hwnd:1,GetMenuItemCount=lambda menu:len(menus[menu]),
                                 GetMenuStringW=text,GetMenuState=lambda menu,index,flags:menus[menu][index]['state'],
                                 GetSubMenu=lambda menu,index:menus[menu][index].get('submenu',0),
                                 GetMenuItemID=lambda menu,index:menus[menu][index].get('id',0xFFFFFFFF))
    result=backend._menus(345)
    management=[item for item in result if item['path'][0]=='管理(&M)']
    assert len(management)==child_count+1
    assert all(item['enabled'] is (not disabled) for item in management)
    assert [item['id'] for item in management[1:]]==list(range(100,100+child_count))
    reload=next(item for item in result if item['path']==['控制(&C)','重新加载(&R)','怪物数据库(&M)'])
    assert reload['id']==900 and reload['enabled'] and not reload['submenu']
    assert all(item['path']!=[''] and item['id']!=0 for item in result)


@pytest.mark.parametrize('action', [{'kind':'key','key':'CTRL+S'}, {'kind':'key','key':'A'}, {'kind':'key','key':'HOME','count':3},
                                    {'kind':'set-text','controlHwnd':14,'expectedClass':'TButton','expectedText':'保存','value':'x'},
                                    {'kind':'menu','path':'选项->怪物'}, {'kind':'visual-click','x':0,'y':0,'button':'middle'}])
def test_unsupported_or_ambiguous_actions_rejected_before_focus(tmp_path,action):
    d=Desktop(); req=action_request(tmp_path,d,action)
    with pytest.raises((ValueError,PermissionError)): module().run_window(req,backend=d)
    assert not d.events and d.front == 999


def relationship_desktop(extra_forms):
    """Keep snapshot/blocking derivation real; fake only Win32 and process reads."""
    from ctypes import wintypes
    from types import SimpleNamespace
    m=module(); d=Desktop(); backend=object.__new__(m.Win32WindowBackend)
    backend.w=wintypes
    forms=[dict(d.target),*copy.deepcopy(extra_forms)]
    by_handle={item['hwnd']:item for item in forms}
    def process(hwnd,result):
        result._obj.value=12
        return 1
    def client(hwnd,result):
        result._obj.right,result._obj.bottom=780,560
        return True
    backend.user=SimpleNamespace(GetWindowThreadProcessId=process,GetClientRect=client,
                                 GetParent=lambda hwnd:by_handle.get(hwnd,{}).get('parent',0),
                                 IsIconic=lambda hwnd:False)
    backend.exists=lambda hwnd:hwnd in by_handle
    backend.native_forms=lambda pid:copy.deepcopy(forms)
    def basic(hwnd):
        item=copy.deepcopy(by_handle[hwnd]); item['text']=item.pop('title')
        return item
    backend._basic=basic
    backend._process=lambda pid:{key:d.target[key] for key in ('executable','sha256','processCreated')}
    backend._hosting=lambda pid,hwnd,identity:None
    backend.client_to_screen=d.client_to_screen
    controls=copy.deepcopy(d.target['controls'])
    controls.extend(dict(item,text=item['title']) for item in extra_forms if item['style'] & 0x40000000)
    backend._controls=lambda hwnd:copy.deepcopy(controls)
    backend._menus=lambda hwnd:copy.deepcopy(d.target['menus'])
    d.snapshot=backend.snapshot
    d.native_forms=backend.native_forms
    return d


@pytest.mark.parametrize('rect',[[287,285,287,683],[287,285,487,683]])
@pytest.mark.parametrize('style',[0x5000044C,0x50000000])
def test_native_child_dialog_is_a_control_not_an_independent_modal(tmp_path,rect,style):
    child={'hwnd':400,'parent':345,'owner':0,'class':'#32770','title':'',
           'style':style,'rect':rect,'visible':True,'enabled':True}
    d=relationship_desktop([child])
    observation=module().run_window(request(tmp_path),backend=d)
    assert observation['target']['blockingWindows']==[]
    assert any(item['hwnd']==400 for item in observation['target']['controls'])
    assert any(item['hwnd']==400 for item in observation['forms'])
    assert observation['screenshot']['hwnd']==345
    req=request(tmp_path,'window-action','action')
    req['arguments'].update(observationReceipt=observation['observationReceipt'],
                            observationSha256=observation['observationSha256'],
                            action={'kind':'key','key':'HOME'})
    result=module().run_window(req,backend=d)
    assert result['actionAttempted'] and not d.held


@pytest.mark.parametrize('rect',[[287,285,287,683],[287,285,487,683]])
def test_owned_dialog_still_blocks_even_when_it_has_no_width(tmp_path,rect):
    modal={'hwnd':400,'parent':345,'owner':345,'class':'#32770','title':'确认',
           'style':0x90C800C4,'rect':rect,'visible':True,'enabled':True}
    d=Desktop(); req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    live=relationship_desktop([modal]); d.snapshot=live.snapshot
    with pytest.raises(ValueError,match='modal'):
        module().run_window(req,backend=d)
    assert not d.events


def test_child_dialog_cannot_hide_a_separate_owned_modal():
    child={'hwnd':400,'parent':345,'owner':0,'class':'#32770','title':'',
           'style':0x5000044C,'rect':[287,285,287,683],'visible':True,'enabled':True}
    modal={'hwnd':401,'parent':345,'owner':345,'class':'TCustomWarning','title':'确认',
           'style':0x90C800C4,'rect':[300,300,500,450],'visible':True,'enabled':True}
    d=relationship_desktop([child,modal])
    assert [item['hwnd'] for item in d.snapshot(12,345)['blockingWindows']]==[401]


@pytest.mark.parametrize('field',['visible','enabled'])
def test_unavailable_native_dialog_does_not_authorize_input(tmp_path,field):
    d=relationship_desktop([])
    d.snapshot.__self__._basic=lambda hwnd:dict(d.target,text=d.target['title'],**{field:False})
    req=action_request(tmp_path,d,{'kind':'key','key':'HOME'})
    with pytest.raises(ValueError):
        module().run_window(req,backend=d)
    assert not d.events


def test_native_relationship_snapshot_rejects_another_process():
    d=relationship_desktop([])
    def other_process(hwnd,result):
        result._obj.value=99
        return 1
    d.snapshot.__self__.user.GetWindowThreadProcessId=other_process
    with pytest.raises(ValueError,match='another process'):
        d.snapshot(12,345)
