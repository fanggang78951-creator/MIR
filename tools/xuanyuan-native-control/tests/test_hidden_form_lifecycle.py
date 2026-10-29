"""Native BM_CLICK may hide a verified form while retaining its HWND."""
import copy
import json
from pathlib import Path
import pytest
from test_native_window import module
from test_stack_component_window import ComponentDesktop, COMPONENTS, request as stack_request

COMPONENT = COMPONENTS[1]

class HiddenFormDesktop(ComponentDesktop):
    def __init__(self, change=None, destroy=False, timeout=False):
        super().__init__(COMPONENT)
        self.nodes[345].update({'class': 'TfrmGeneralConfig', 'text': '基本设置', 'style': 0x16CF0000})
        self.nodes[14]['text'] = '确定(&O)'
        self.nodes[346] = self.node(346, 'TFrmMain', 'RunGate', style=0x16CF0000)
        self.nodes[346]['enabled'] = False
        self.pids[346], self.parents[346] = 12, 0
        self.change, self.destroy, self.timeout = change, destroy, timeout
        self.native._class = lambda hwnd: self.nodes[hwnd]['class']
        self.native.root = lambda hwnd: hwnd if hwnd in (345, 346, 999) else 345
        self.native.user.IsWindowVisible = lambda hwnd: self.nodes[hwnd]['visible']
        self.lifecycle_queries = 0

    def native_forms(self, pid):
        result = []
        for hwnd in (345, 346):
            if hwnd not in self.nodes: continue
            n = self.nodes[hwnd]
            if not n['visible'] and n['class'].lower() != 'tfrmmain': continue
            item = self.basic(hwnd); item['title'] = item.pop('text'); result.append(item)
        return result

    def enum_children(self, hwnd, callback, unused):
        if hwnd == 346: return True
        return super().enum_children(hwnd, callback, unused)

    def send_message_timeout(self, hwnd, message, wparam, lparam, flags, timeout, result):
        accepted = super().send_message_timeout(hwnd, message, wparam, lparam, flags, timeout, result)
        if message == 0xF5:
            if self.destroy:
                del self.nodes[345]
            else:
                self.nodes[345]['visible'] = False
                self.nodes[345]['style'] &= ~0x10000000
                if self.change:
                    key, value = self.change
                    if key == 'pid': self.pids[345] = value
                    elif key in ('processCreated','sha256','executable'): self.identities[12][key] = value
                    elif key == 'parent': self.parents[345] = value
                    else: self.nodes[345][key] = value
            self.nodes[346]['enabled'] = True
            self.front, self.hit = 346, 346
            if self.timeout: return 0
        return accepted

    def post_action_lifecycle(self, previous):
        self.lifecycle_queries += 1
        assert hasattr(self.native, 'post_action_lifecycle'), 'restricted post-action lifecycle is missing'
        return self.native.post_action_lifecycle(previous)


def req(tmp_path, desktop, command='window-observe', name='observe'):
    result = stack_request(tmp_path, COMPONENT, command=command, name=name)
    result['arguments'].update(expectedClass='TfrmGeneralConfig', expectedTitle='基本设置')
    return result


def prepare(tmp_path, desktop, synchronous=True):
    seen = module().run_window(req(tmp_path, desktop), backend=desktop)
    result = req(tmp_path, desktop, 'window-action', 'action')
    result['arguments'].update(observationReceipt=seen['observationReceipt'], observationSha256=seen['observationSha256'],
                               action={'kind':'button','controlHwnd':14,'expectedClass':'TButton','expectedText':'确定(&O)','synchronous':synchronous})
    return result


def test_ack_then_hidden_existing_form_reports_lifecycle_without_reusable_target(tmp_path):
    d = HiddenFormDesktop(); data = module().run_window(prepare(tmp_path, d), backend=d)
    assert d.exists(345) and not d.nodes[345]['visible']
    assert d.button_count == 1 and [m[1] for m in d.messages] == [0xF5]
    assert data['actionAttempted'] and data['dispatch']['handlerAcknowledged']
    assert data['target'] is None and data['targetClosed'] is False
    assert data['targetLifecycle']['state'] == 'hidden' and data['targetLifecycle']['exists'] is True
    assert data['continuation']['requiresFreshObservation'] is True
    assert any(f['hwnd'] == 346 for f in data['continuation']['candidateForms'])
    assert data['screenshot']['hwnd'] == 346
    assert data['businessSaveVerified'] is False and data['readbackVerified'] is False
    assert d.lifecycle_queries == 1
    # The action result is an outcome receipt, not new input authority for a hidden form.
    with pytest.raises(ValueError, match='observed native form'):
        d.snapshot(12, 345)
    follow = stack_request(tmp_path, COMPONENT, name='main-observe')
    follow['arguments'].update(hwnd=346, expectedClass='TFrmMain', expectedTitle='RunGate')
    assert module().run_window(follow, backend=d)['target']['hwnd'] == 346
    assert d.button_count == 1


def test_destroyed_window_is_distinct_from_hidden(tmp_path):
    d = HiddenFormDesktop(destroy=True); data = module().run_window(prepare(tmp_path,d),backend=d)
    assert data['target'] is None and data['targetClosed'] is True
    assert data['targetLifecycle']['state'] == 'destroyed' and data['targetLifecycle']['exists'] is False
    assert d.button_count == 1 and d.lifecycle_queries == 0


@pytest.mark.parametrize('change',[('pid',88),('processCreated','13370002'),('sha256','0'*64),
    ('executable',r'E:\another\RunGate.exe'),('class','TEdit'),('text','different'),('parent',346),('owner',346),('style',0x40000000)])
def test_hidden_identity_drift_is_not_converted_to_success(tmp_path,change):
    d=HiddenFormDesktop(change=change); request=prepare(tmp_path,d)
    with pytest.raises((ValueError,PermissionError)):module().run_window(request,backend=d)
    failure=json.loads((tmp_path/'action/failure.json').read_text('utf-8'))
    assert failure['actionAttempted'] and failure['dispatch']['handlerAcknowledged']
    assert d.button_count == 1


def test_hidden_form_without_current_action_is_still_not_observable(tmp_path):
    d=HiddenFormDesktop(); d.nodes[345]['visible']=False
    with pytest.raises(ValueError,match='observed native form'):
        module().run_window(req(tmp_path,d),backend=d)
    assert not d.messages and not d.lifecycle_queries


def test_timeout_after_single_dispatch_stays_failed_and_is_not_retried(tmp_path):
    d=HiddenFormDesktop(timeout=True); request=prepare(tmp_path,d)
    with pytest.raises(TimeoutError):module().run_window(request,backend=d)
    failure=json.loads((tmp_path/'action/failure.json').read_text('utf-8'))
    assert failure['actionAttempted'] and failure['dispatch'] is None
    assert d.button_count==1 and d.lifecycle_queries==0


def test_lifecycle_result_is_not_input_authority_for_the_main_form(tmp_path):
    d=HiddenFormDesktop(); outcome=module().run_window(prepare(tmp_path,d),backend=d)
    follow=stack_request(tmp_path,COMPONENT,command='window-action',name='must-reobserve')
    follow['arguments'].update(hwnd=346,expectedClass='TFrmMain',expectedTitle='RunGate',
        observationReceipt=outcome['observationReceipt'],observationSha256=outcome['observationSha256'],action={'kind':'show'})
    with pytest.raises(ValueError,match='changed since observation'):
        module().run_window(follow,backend=d)
    assert d.button_count==1


def test_hidden_lifecycle_never_queries_controls_or_menus(tmp_path):
    d=HiddenFormDesktop(); request=prepare(tmp_path,d)
    old_controls,old_menus=d.native._controls,d.native._menus
    def controls(hwnd):
        assert hwnd != 345 or d.nodes[345]['visible'], 'hidden controls must not be queried'
        return old_controls(hwnd)
    def menus(hwnd):
        assert hwnd != 345 or d.nodes[345]['visible'], 'hidden menus must not be queried'
        return old_menus(hwnd)
    d.native._controls,d.native._menus=controls,menus
    assert module().run_window(request,backend=d)['targetLifecycle']['postActionOnly']


@pytest.mark.parametrize('change',['title','visible','pid','creation','destroyed','root','truncated'])
def test_hidden_lifecycle_second_sample_drift_is_rejected(tmp_path,change):
    d=HiddenFormDesktop();before=module().run_window(req(tmp_path,d),backend=d)['target']
    d.nodes[345]['visible']=False;d.nodes[345]['style'] &= ~0x10000000
    basic=d.native._basic; calls=[]
    def changed(hwnd):
        item=basic(hwnd);calls.append(hwnd)
        if len(calls)==1:
            if change=='title':d.nodes[345]['text']='changed'
            elif change=='visible':d.nodes[345]['visible']=True
            elif change=='pid':d.pids[345]=88
            elif change=='creation':d.identities[12]['processCreated']='999'
            elif change=='destroyed':del d.nodes[345]
            elif change=='root':d.native.root=lambda hwnd:999
            else:item['textTruncated']=True
        return item
    d.native._basic=changed
    assert hasattr(d.native,'post_action_lifecycle')
    with pytest.raises((ValueError,PermissionError)):
        d.native.post_action_lifecycle(before)
    assert not d.messages


def test_hidden_main_is_only_a_fresh_observation_candidate_not_new_authority(tmp_path):
    d=HiddenFormDesktop();original=d.send_message_timeout
    def send(*args):
        accepted=original(*args)
        if args[1]==0xF5:d.nodes[346]['visible']=False
        return accepted
    d.native.user.SendMessageTimeoutW=send
    result=module().run_window(prepare(tmp_path,d),backend=d)
    assert result['target'] is None and not result['targetClosed'] and result['screenshot'] is None
    assert result['continuation']['requiresFreshObservation']
    assert any(form['hwnd']==346 and form['visible'] is False for form in result['continuation']['candidateForms'])
    assert d.button_count==1


@pytest.mark.parametrize('prior_change',[('hosting',{'rootHwnd':700}),('textTruncated',True)])
def test_hidden_metadata_rejects_prior_hosting_or_truncated_title(prior_change):
    d=HiddenFormDesktop();previous=d.snapshot(12,345);observed=copy.deepcopy(previous)
    observed.update(visible=False,style=previous['style'] & ~0x10000000,rootHwnd=345,textTruncated=False)
    previous[prior_change[0]]=prior_change[1]
    with pytest.raises(ValueError):module()._hidden_after_action(previous,observed)
