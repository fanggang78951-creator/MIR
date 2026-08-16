# Monster and Drop Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 LFM2/MirServer 中安全新增一个经过指定的怪物定义、刷怪配置和对应 MonItems 爆率表，并保留可回滚证据。

**Architecture:** 以当前服 `D:\MirServer\Mud2\DB\ApexM2.DB` 的 SQLite `Monster` 表为怪物属性权威来源；以 `D:\MirServer\Mir200\Envir\MonGen.txt` 控制地图刷新；以 `D:\MirServer\Mir200\Envir\MonItems\<怪物名>.txt` 控制掉落。源包只提供候选属性、编码和格式参考，不能整库覆盖当前服。

**Tech Stack:** Python 3 `sqlite3` 只写事务、PowerShell/GBK 文本校验、LFM2 M2 静态加载检查、游戏内最小验收。

## Global Constraints

- 目标服固定为 `D:\MirServer`，除非用户明确指定其他目标。
- 当前服使用 `!setup.txt` 中的 SQLite `D:\MirServer\Mud2\DB\ApexM2.DB`，不直接改旧式 `Monster.DB` 二进制。
- 源包 `D:\素材文件夹\明月地图补丁\77boss是解压码MirServer\MirServer` 只读参考，不整库覆盖。
- 任何数据库、`MonGen.txt`、`MonItems` 或核心脚本修改前必须取得用户确认并建立带时间戳备份。
- 不猜测怪物名称、地图代码、坐标、外观编号、属性数值、掉落物品或爆率。
- 不主动修改客户端 PAK/WZL/WZX、`MonSpAbilList.txt`、`SmartMonster` 或 `MonUseItems`，除非选定怪物确实需要且用户确认。
- 文本文件保持原编码；当前探测确认本服 `MonGen.txt`/`MonItems` 使用 GBK 兼容链路。

---

### Task 1: Lock the monster specification

**Files:**
- Read: `D:\素材文件夹\明月地图补丁\77boss是解压码MirServer\MirServer\Mud2\DB\ApexM2.db`
- Read: `D:\素材文件夹\明月地图补丁\77boss是解压码MirServer\MirServer\Mir200\Envir\MonItems`
- Read: `D:\MirServer\Mud2\DB\ApexM2.db`
- Read: `D:\MirServer\Mir200\Envir\MonGen.txt`

**Required inputs before writing:**
- 怪物显示名；若沿用源包模板，提供源包怪物名。
- 地图代码、中心坐标 X/Y、刷新范围、数量、刷新间隔、名称颜色。
- 是否使用源包外观；若使用，提供已确认客户端资源编号/补丁来源。
- 属性来源：源包某个怪物整行，或用户逐项指定 `Race/RaceImg/Appr/Lvl/Exp/HP/MP/AC/MAC/DC/DCMAX/MC/SC/SPEED/HIT/WALK_SPD/WalkStep/WaLkWait/ATTACK_SPD/AttackState/AttackSource`。
- 掉落表逐行提供 `分子/分母 物品名`；需要分组随机时明确 `#CHILD` 的门槛和 `RANDOM/BURSTRATE` 语义。

- [ ] Confirm the target monster name and source/template row.
- [ ] Confirm the exact `MonGen.txt` spawn line values.
- [ ] Confirm whether client resource work is in scope.
- [ ] Confirm the complete drop list and group semantics.

### Task 2: Preflight and backup

**Files:**
- Read: `D:\MirServer\Mir200\!setup.txt`
- Read: `D:\MirServer\Mud2\DB\ApexM2.db`
- Read: `D:\MirServer\Mir200\Envir\MonGen.txt`
- Read: `D:\MirServer\Mir200\Envir\MonItems\<怪物名>.txt`
- Create: `D:\MirServer\Backup\MonsterDrop_<timestamp>\`

- [ ] Verify M2 is stopped or obtain an explicit maintenance window before touching SQLite.
- [ ] Record SHA-256 and file size for the target database, `MonGen.txt`, and any existing drop file.
- [ ] Copy each target file to the timestamped backup directory, preserving relative paths.
- [ ] Verify the backup hashes equal the pre-change hashes.
- [ ] Check that the new monster name does not already exist in the SQLite `Monster` table or `MonGen.txt`.

### Task 3: Write the minimal monster definition

**Files:**
- Modify: `D:\MirServer\Mud2\DB\ApexM2.db` (`Monster` table only)

- [ ] Open a SQLite transaction and insert exactly one `Monster` row using the confirmed values.
- [ ] Do not update or delete existing monster rows.
- [ ] Verify the inserted row has the expected name and all 24 core fields.
- [ ] Commit only after the row-level verification succeeds; otherwise roll back.

### Task 4: Add the spawn and drop configuration

**Files:**
- Modify: `D:\MirServer\Mir200\Envir\MonGen.txt`
- Create or modify: `D:\MirServer\Mir200\Envir\MonItems\<怪物名>.txt`

- [ ] Append one GBK-encoded `MonGen.txt` line using the confirmed map, coordinates, range, count, interval, concentrated-spawn rate and name color.
- [ ] Create the drop file with one confirmed entry per line, preserving `#CHILD` blocks exactly where specified.
- [ ] Reject any item name not found in the target `StdItems` table unless the user explicitly authorizes adding that item first.
- [ ] Verify the monster name in `MonGen.txt` exactly matches the SQLite `Monster.Name` and the `MonItems` filename stem.

### Task 5: Static validation and controlled load test

**Files:**
- Read: `D:\MirServer\Mud2\DB\ApexM2.db`
- Read: `D:\MirServer\Mir200\Envir\MonGen.txt`
- Read: `D:\MirServer\Mir200\Envir\MonItems\<怪物名>.txt`
- Read: M2 startup log produced by the test restart

- [ ] Re-query the inserted SQLite row and compare every field against the approved specification.
- [ ] Validate `MonGen.txt` column count and numeric fields.
- [ ] Validate every drop line, group header, item name and probability denominator.
- [ ] Start M2 in the approved maintenance window and confirm the Monster database loads without a parser error.
- [ ] In game, verify the monster is visible, has the intended appearance, spawns at the intended location, respawns, and drops only the approved table entries.
- [ ] If any check fails, stop and restore the backed-up files; do not layer a second unverified fix.

### Task 6: Handoff record

**Files:**
- Create: `D:\codex交班记录\YYYYMMDD_HHMM_制造怪物与爆率表.txt`
- Modify: `D:\codex交班记录\00_任务总结索引.txt`
- Modify: `D:\codex交班记录\01_最近任务指针.txt`

- [ ] Record the approved specification, all read/modified files, backup path, hashes, actual commands, validation results, risks and next-game-test advice.
- [ ] Use exactly one status: `已完成`、`部分完成`、`失败`、`中断`、`待验证`。
- [ ] Update the summary index and recent pointer without rewriting unrelated history.
