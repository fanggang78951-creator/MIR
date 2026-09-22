from __future__ import annotations

from pathlib import Path


STAR13_ACTIONS = {
    "ActStand": (1340, 4, 6, 1),
    "ActWalk": (1420, 6, 4, 1),
    "ActStruck": (1580, 2, 0, 1),
    "ActDie": (1600, 10, 0, 1),
    "ActAttack1": (1500, 6, 4, 1),
}


def write_wzl_wzx_pair(
    root: Path,
    stem: str,
    actions: dict[str, tuple[int, int, int, int]] = STAR13_ACTIONS,
    frame_type: int = 259,
) -> tuple[Path, Path]:
    """Create a minimal 1700-entry monster WZL/WZX pair with playable action frames."""
    root.mkdir(parents=True, exist_ok=True)
    offsets = [0] * 1700
    wzl = bytearray(b"\0" * 48)
    for start, play_count, empty_count, calc_dir in actions.values():
        directions = 8 if calc_dir == 1 else 1
        stride = play_count + empty_count
        for direction in range(directions):
            for frame in range(play_count):
                index = start + direction * stride + frame
                offset = len(wzl)
                offsets[index] = offset
                wzl.extend(frame_type.to_bytes(2, "little"))
                wzl.extend(b"\0\0")
    wzx = bytearray(b"\0" * 48)
    wzx[44:48] = (1700).to_bytes(4, "little")
    for offset in offsets:
        wzx.extend(offset.to_bytes(4, "little"))
    wzl_path = root / f"{stem}.wzl"
    wzx_path = root / f"{stem}.wzx"
    wzl_path.write_bytes(bytes(wzl))
    wzx_path.write_bytes(bytes(wzx))
    return wzl_path, wzx_path


def write_smartmonster_ini(
    path: Path, resource_index: int = 78, *, extra_attack: bool = False
) -> Path:
    """Write the golden basic-melee SmartMonster shape with 13 resource references."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[ServerAttack0]",
        "AttackEnabled=1",
        "AttackMode=0",
        "[ServerAttack1]",
        f"AttackEnabled={1 if extra_attack else 0}",
        "AttackMode=0",
    ]
    for index in range(2, 6):
        lines.extend((f"[ServerAttack{index}]", "AttackEnabled=0", "AttackMode=0"))
    for section, (start, play, empty, calc_dir) in STAR13_ACTIONS.items():
        lines.extend((
            f"[{section}]",
            f"StartIndex={start}",
            f"PlayCount={play}",
            f"EmptyCount={empty}",
            f"CalcDir={calc_dir}",
            f"ActionFile={resource_index}",
        ))
    for index in range(7):
        lines.extend((f"[ActionVariant{index}]", f"ActionFile={resource_index}"))
    lines.extend(("[EffectAttack]", f"EffectFile={resource_index}"))
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("gb18030"))
    return path


def write_effect_image_list(path: Path, entries: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\r\n".join(entries) + "\r\n").encode("gb18030"))
    return path
