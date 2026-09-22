# WZX Unequal Library Counts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复静态装备图标工具对三套 WZX 历史数量必须相等的错误假设。

**Architecture:** 读取来源时独立验证每套图库；写入时选择最大物理槽数作为共同 Looks，短库补零后分别追加原始帧。客户端二进制修改前备份，失败恢复。

**Tech Stack:** Python 3.12、stdlib struct/shutil/hashlib、unittest、PyInstaller。

## Global Constraints

- 不修改装备属性、数据库字段或 QFunction 逻辑。
- 不直接写真实客户端做算法验证。
- Items/StateItem/DnItems 新帧必须分别来自各自来源帧。

---

### Task 1: 失败测试与来源读取

**Files:**
- Modify: `做装备/tests/test_equipment_resources.py`
- Modify: `做装备/src/xyequip/legacy/xy_equip_maker.py`

**Interfaces:**
- Consumes: `read_wzx_count_and_offset(Path, int) -> int`
- Produces: 允许头部 count 与物理槽数不同，并移除三库 count 相等要求。

- [ ] 写合成 WZX 头部少 1 但来源偏移有效的失败测试。
- [ ] 运行测试，确认因现有严格 count 校验失败。
- [ ] 以物理槽数验证来源编号和偏移，不比较三库历史 count。
- [ ] 运行测试确认通过。

### Task 2: 不等长三图库统一追加

**Files:**
- Modify: `做装备/tests/test_equipment_resources.py`
- Modify: `做装备/src/xyequip/resources/clone_wzl_frame_raw.py`

**Interfaces:**
- Consumes: 三套独立 `offsets` 与原始帧。
- Produces: `target_id=max(counts_before)`；`append_raw_frame(..., target_id, frame)` 可补零并追加。

- [ ] 写 4/2/3 槽合成库测试，断言共同 Looks=4、结果均为 5 槽、短库补位为 0。
- [ ] 运行测试确认现有“三库 count 不一致”错误。
- [ ] 放宽读取头部差异，移除三库相等判断，追加前补零到 target_id。
- [ ] 添加异常恢复六文件逻辑。
- [ ] 运行资源测试确认通过。

### Task 3: 读回验证与交付

**Files:**
- Modify: `做装备/src/xyequip/legacy/xy_equip_maker.py`
- Modify: `codex交班记录/玄渊成果植入平台_完整使用说明_ChatGPT必读.txt`

**Interfaces:**
- Consumes: `result.json counts_before` 可不相等。
- Produces: 导入后每套 count/header 均等于 `target_id + 1`，帧 SHA-256 分别一致。

- [ ] 更新旧核心读回校验，不再要求 counts_before 相等，要求 target_id 等于其最大值。
- [ ] 在真实客户端上只读预检来源 1404，确认不再出现 count 阻止。
- [ ] 运行 56 项平台测试和全部装备测试。
- [ ] 构建更新版 GUI/CLI 并烟雾测试。
- [ ] 写交班记录，保持模块 candidate，等待游戏内图标验证。
