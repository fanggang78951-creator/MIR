"""Failure-only guard diagnostics retain the original ordered OS-boundary checks."""
import copy
import json

import pytest

from test_native_window import Desktop, action_request, module, request


FOCUS_ERROR = 'Native focus or point ownership changed'
ANCESTRY_ERROR = 'Point ancestor chain does not reach the selected native form'
MEMBERSHIP_ERROR = 'Point belongs to the host or another native form, not the selected form'


class GuardBoundary:
    """Only the existing guard queries, each recorded once when actually evaluated."""

    def __init__(self, fail=None):
        self.fail, self.calls, self.foregrounds = fail, [], 0

    def root(self, hwnd):
        self.calls.append(('root', hwnd))
        return 345

    def foreground(self):
        self.calls.append(('foreground',))
        self.foregrounds += 1
        return 888 if self.fail == ('foregroundBefore' if self.foregrounds == 1 else 'foregroundAfter') else 345

    def root_at(self, point):
        self.calls.append(('root_at', list(point)))
        return 888 if self.fail == 'pointRoot' else 345

    def observation_point_in_form(self, hwnd, point):
        self.calls.append(('observation_point_in_form', hwnd, list(point)))
        return self.fail != 'observationMembership'

    def point_in_form(self, hwnd, point):
        self.calls.append(('point_in_form', hwnd, list(point)))
        return self.fail != 'inputMembership'


CALLS = [('root', 345), ('foreground',), ('root_at', [70, 110]), ('foreground',),
         ('observation_point_in_form', 345, [70, 110]), ('point_in_form', 345, [70, 110])]


@pytest.mark.parametrize('failure,count,error,values', [
    ('foregroundBefore', 2, FOCUS_ERROR, (888, None, None)),
    ('pointRoot', 3, FOCUS_ERROR, (345, 888, None)),
    ('foregroundAfter', 4, FOCUS_ERROR, (345, 345, 888)),
    ('observationMembership', 5, ANCESTRY_ERROR, (345, 345, 345)),
    ('inputMembership', 6, MEMBERSHIP_ERROR, (345, 345, 345)),
])
@pytest.mark.parametrize('collect', [False, True])
def test_guard_short_circuit_keeps_exact_query_order_counts_and_original_error(failure, count, error, values, collect):
    backend = GuardBoundary(failure)
    evidence = {} if collect else None
    with pytest.raises(ValueError) as caught:
        module()._guard(backend, Desktop().target, [70, 110], require_membership=True,
                        evidence=evidence, stage='pre-move')
    assert str(caught.value) == error
    assert backend.calls == CALLS[:count]
    if collect:
        assert evidence['firstFailedCheck'] == failure
        assert (evidence['foregroundBefore'], evidence['pointRoot'], evidence['foregroundAfter']) == values
        assert evidence['stage'] == 'pre-move' and evidence['pointScreen'] == [70, 110]
        assert evidence['targetHwnd'] == 345 and evidence['targetRootHwnd'] == 345
        assert evidence['clientOrigin'] == [20, 50] and evidence['clientSize'] == [780, 560]
        assert evidence['requireMembership'] is True


@pytest.mark.parametrize('membership,count', [(False, 5), (True, 6)])
def test_successful_guard_has_no_extra_reads_and_clears_previous_failure(membership, count):
    backend = GuardBoundary()
    evidence = {'firstFailedCheck': 'old-error', 'pointerMoveAttempted': True, 'pointerMoveVerified': True}
    module()._guard(backend, Desktop().target, [70, 110], require_membership=membership,
                    evidence=evidence, stage='capture-after')
    assert backend.calls == CALLS[:count]
    assert evidence['firstFailedCheck'] is None and evidence['requireMembership'] is membership
    assert evidence['pointerMoveAttempted'] and evidence['pointerMoveVerified']


def trace_guards(monkeypatch, *, fail_stage=None):
    original, calls = module()._guard, []

    def guard(backend, target, point, **options):
        if options.get('stage') == fail_stage and fail_stage is not None:
            backend.covered = True
        try:
            return original(backend, target, point, **options)
        finally:
            calls.append(copy.deepcopy(options.get('evidence')))

    monkeypatch.setattr(module(), '_guard', guard)
    return calls


def failure_data(tmp_path):
    return json.loads((tmp_path / 'action' / 'failure.json').read_text('utf-8'))


@pytest.mark.parametrize('stage,point,moved,attempted', [
    ('initial-center', [410, 330], False, False),
    ('fresh-center', [410, 330], False, False),
    ('pre-move', [70, 110], False, False),
    ('post-move', [70, 110], True, False),
    ('capture-before', [410, 330], True, True),
    ('capture-after', [410, 330], True, True),
])
def test_run_failure_records_the_actual_guard_stage_and_move_flags(tmp_path, monkeypatch, stage, point, moved, attempted):
    desktop = Desktop()
    req = action_request(tmp_path, desktop, {'kind': 'visual-click', 'x': 50, 'y': 60})
    trace_guards(monkeypatch, fail_stage=stage)
    with pytest.raises(ValueError) as caught:
        module().run_window(req, backend=desktop)
    assert str(caught.value) == FOCUS_ERROR
    failure = failure_data(tmp_path)
    evidence = failure['guardEvidence']
    assert evidence['stage'] == stage and evidence['pointScreen'] == point
    assert evidence['requestedClientPoint'] == [50, 60]
    assert evidence['firstFailedCheck'] == 'pointRoot'
    assert evidence['foregroundBefore'] == 345 and evidence['pointRoot'] == 888
    assert evidence['foregroundAfter'] is None
    assert evidence['pointerMoveAttempted'] is moved and evidence['pointerMoveVerified'] is moved
    assert failure['actionAttempted'] is attempted
    assert len(desktop.events) == (2 if attempted else 0)
    assert not desktop.held and desktop.front == 999 and desktop.pointer == [3, 4]


@pytest.mark.parametrize('action,stages,event_count', [
    (None, ['initial-center', 'capture-before', 'capture-after'], 0),
    ({'kind': 'visual-click', 'x': 50, 'y': 60},
     ['initial-center', 'fresh-center', 'pre-move', 'post-move', 'capture-before', 'capture-after'], 2),
    ({'kind': 'key', 'key': 'HOME'},
     ['initial-center', 'fresh-center', 'pre-input', 'capture-before', 'capture-after'], 2),
    ({'kind': 'set-text', 'controlHwnd': 10, 'expectedClass': 'TEdit', 'expectedText': '12', 'value': '33'},
     ['initial-center', 'fresh-center', 'capture-before', 'capture-after'], 1),
])
def test_successful_observation_and_actions_keep_receipts_and_input_behavior(tmp_path, monkeypatch, action, stages, event_count):
    desktop = Desktop()
    req = action_request(tmp_path, desktop, action) if action else request(tmp_path)
    calls = trace_guards(monkeypatch)
    result = module().run_window(req, backend=desktop)
    assert [evidence['stage'] for evidence in calls] == stages
    assert all(evidence['firstFailedCheck'] is None for evidence in calls)
    assert all(evidence['requestedClientPoint'] == ([50, 60] if action and action['kind'] == 'visual-click' else None)
               for evidence in calls)
    assert 'guardEvidence' not in result
    receipt = json.loads((tmp_path / ('action' if action else 'observe') / 'observation.json').read_text('utf-8'))
    assert 'guardEvidence' not in receipt
    assert len(desktop.events) == event_count and not desktop.held


def test_move_failure_records_attempt_without_claiming_verified_move(tmp_path):
    desktop = Desktop()
    req = action_request(tmp_path, desktop, {'kind': 'visual-click', 'x': 50, 'y': 60})
    moves = []

    def move(point):
        moves.append(list(point))
        raise ValueError('Cursor did not reach the requested location')

    desktop.move = move
    with pytest.raises(ValueError, match='Cursor did not reach'):
        module().run_window(req, backend=desktop)
    failure = failure_data(tmp_path)
    evidence = failure['guardEvidence']
    assert moves == [[70, 110]] and not desktop.events
    assert evidence['stage'] == 'pre-move' and evidence['firstFailedCheck'] is None
    assert evidence['pointerMoveAttempted'] and not evidence['pointerMoveVerified']
    assert not failure['actionAttempted']


@pytest.mark.parametrize('kind', ['key', 'visual-click'])
def test_identity_rejection_before_first_guard_has_no_invented_guard_failure(tmp_path, kind):
    desktop = Desktop()
    action = {'kind': 'key', 'key': 'HOME'} if kind == 'key' else {'kind': 'visual-click', 'x': 50, 'y': 60}
    req = action_request(tmp_path, desktop, action)
    desktop.target['title'] = 'another title'
    with pytest.raises(ValueError, match='Native process/window identity changed'):
        module().run_window(req, backend=desktop)
    evidence = failure_data(tmp_path)['guardEvidence']
    for field in ('stage', 'firstFailedCheck', 'pointScreen', 'targetHwnd', 'targetRootHwnd',
                  'clientOrigin', 'clientSize', 'requireMembership', 'foregroundBefore', 'pointRoot', 'foregroundAfter'):
        assert evidence[field] is None
    assert evidence['requestedClientPoint'] == ([50, 60] if kind == 'visual-click' else None)
    assert not evidence['pointerMoveAttempted'] and not evidence['pointerMoveVerified']
    assert not desktop.events


def test_fresh_identity_rejection_preserves_last_successful_guard_without_blame(tmp_path):
    desktop = Desktop()
    req = action_request(tmp_path, desktop, {'kind': 'key', 'key': 'HOME'})
    original, snapshots = desktop.snapshot, []

    def snapshot(pid, hwnd):
        snapshots.append(hwnd)
        if len(snapshots) == 2:
            desktop.target['title'] = 'another title'
        return original(pid, hwnd)

    desktop.snapshot = snapshot
    with pytest.raises(ValueError, match='Native process/window identity changed'):
        module().run_window(req, backend=desktop)
    failure = failure_data(tmp_path)
    assert failure['guardEvidence']['stage'] == 'initial-center'
    assert failure['guardEvidence']['firstFailedCheck'] is None
    assert not failure['actionAttempted'] and not desktop.events


def test_post_click_title_change_remains_rejected_after_accepted_dispatch(tmp_path):
    desktop = Desktop()
    req = action_request(tmp_path, desktop, {'kind': 'visual-click', 'x': 50, 'y': 60})
    original = desktop.down

    def down(kind, value):
        original(kind, value)
        desktop.target['title'] = 'changed after click'

    desktop.down = down
    with pytest.raises(ValueError, match='Native process/window identity changed'):
        module().run_window(req, backend=desktop)
    failure = failure_data(tmp_path)
    assert failure['actionAttempted'] and failure['dispatch']['accepted']
    assert failure['guardEvidence']['stage'] == 'post-move'
    assert failure['guardEvidence']['firstFailedCheck'] is None
    assert failure['guardEvidence']['pointerMoveAttempted'] and failure['guardEvidence']['pointerMoveVerified']
    assert len(desktop.events) == 2 and not desktop.held


@pytest.mark.parametrize('kind', ['key', 'visual-click'])
def test_existing_keyboard_focus_and_mouse_client_bounds_still_reject(tmp_path, kind):
    desktop = Desktop()
    action = {'kind': 'key', 'key': 'HOME'} if kind == 'key' else {'kind': 'visual-click', 'x': 780, 'y': 60}
    req = action_request(tmp_path, desktop, action)
    desktop.focus_in_form = lambda hwnd: False
    with pytest.raises(ValueError, match='Keyboard focus' if kind == 'key' else 'outside the native client area'):
        module().run_window(req, backend=desktop)
    failure = failure_data(tmp_path)
    evidence = failure['guardEvidence']
    assert evidence['stage'] == 'fresh-center' and evidence['firstFailedCheck'] is None
    assert not evidence['pointerMoveAttempted'] and not evidence['pointerMoveVerified']
    assert not failure['actionAttempted'] and not desktop.events
