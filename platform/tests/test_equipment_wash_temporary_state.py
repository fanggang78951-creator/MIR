"""Small command interpreter checks persistent per-player scratch-state reuse.

The interpreter consumes emitted MOV/CALL/condition/custom-row writes. Random
selection is a deterministic stub, so these tests isolate stale slot state.
"""
import re
import unittest
from pathlib import Path
from xydp.equipment_wash import render_main_script, render_direct_script

ROOT = Path(__file__).resolve().parents[1]


def section(script, label):
    return re.split(r'(?m)^\[@[^\]]+\]', script.split(f'[@{label}]', 1)[1])[0]


def execute(script, state, written):
    active = True
    def value(token):
        match = re.fullmatch(r'<\$STR\((N\$[^)]+)\)>', token)
        if match: return state.get(match[1], 0)
        if token.startswith('N$'): return state.get(token, 0)
        try: return int(token)
        except ValueError: return 0
    for raw in script.splitlines():
        line = raw.strip(); words = line.split()
        if not words: continue
        cmd = words[0].upper()
        if cmd == '#IF': active = True
        elif cmd in ('LARGE', 'EQUAL') and len(words) == 3:
            active = active and (value(words[1]) > value(words[2]) if cmd == 'LARGE' else value(words[1]) == value(words[2]))
        elif cmd == '#ELSEACT': active = not active
        elif cmd == 'MOV' and len(words) == 3 and active and words[1].startswith('N$XY_WASH_'):
            state[words[1]] = value(words[2])
        elif cmd == '#CALL' and active and '@XY_WASH_PICK_' in line:
            state.update({'N$XY_WASH_PICK_LINE': 43, 'N$XY_WASH_PICK_VALUE': 7, 'N$XY_WASH_PICK_NATIVE': -1})
        elif cmd == 'SETCUSTOMITEMVALUEEX' and active:
            written[int(words[2])] = (value(words[4]), value(words[5]))


def direct_cycle(box, stars, state):
    script = render_direct_script('PUBLIC', box, '品质', 242, stars, '成功')
    # Only the initialization and row-writing contracts are interpreted here.
    # Selected-slot values stand in for the CALL results, without emulating the engine.
    execute(script.split('#CALL', 1)[0], state, {})
    for i in range(stars):
        state.update({f'N$XY_WASH_LINE{i}': 43, f'N$XY_WASH_VALUE{i}': 7, f'N$XY_WASH_NATIVE{i}': -1})
    written = {}
    execute('#IF\n#ACT\n' + script.rsplit(f'SetUpgradeItem {box}', 1)[1], state, written)
    return written


class WashTemporaryStateTests(unittest.TestCase):
    def test_eight_affixes_then_low_count_wash_does_not_write_stale_slots(self):
        template = (ROOT / 'packages/verified/xy.optional.equipment-wash-opening/payload/server/npc/装备洗练.txt').read_text(encoding='utf-8').format_map({})
        main = render_main_script(template)
        state = {}
        written = direct_cycle(28, 8, state)
        self.assertEqual(set(written), set(range(8)))
        # Run the next paid wash's actual initialization, then its two selected slots.
        execute(main.split('[@区分级别洗练]', 1)[0], state, {})
        execute(section(main, '获取属性一'), state, {})
        execute(section(main, '获取属性二'), state, {})
        written = {}
        execute(section(main, '洗练给予属性'), state, written)
        self.assertEqual(set(written), {0, 1}, '低条数洗练不得沿用上次的3至8槽')
        self.assertTrue(all(state[f'N$XY_WASH_NATIVE{i}'] == -1 for i in range(2, 8)))

    def test_box27_and_box28_direct_entries_clear_unused_slots_in_both_directions(self):
        state = {f'N$XY_WASH_{kind}{i}': 999 for kind in ('LINE', 'VALUE', 'NATIVE') for i in range(8)}
        for box, stars in ((28, 8), (27, 5), (28, 7), (27, 6)):
            written = direct_cycle(box, stars, state)
            self.assertEqual(set(written), set(range(stars)))
            for i in range(stars, 8):
                self.assertEqual(state[f'N$XY_WASH_LINE{i}'], 0)
                self.assertEqual(state[f'N$XY_WASH_VALUE{i}'], 0)
                self.assertEqual(state[f'N$XY_WASH_NATIVE{i}'], -1)
