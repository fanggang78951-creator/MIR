# 战斗属性运行时刷新修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让神力倍攻、暴击伤害、人物爆率和最大爆率不再依赖不可靠的登录/穿脱一次性刷新，而是在已验证触发的 AttackDamage 事件中按当前穿戴实时重算。

**Architecture:** 新增 `xy.combat.runtime-refresh` 公共成果包，在 `[@AttackDamage]` 插入一次受管运行时刷新块并提供四个装备扩展锚点。装备属性注册表为倍攻、爆伤、爆率、最大爆率各增加一个运行时出口；原 `XYDP_Recalc*` 与穿脱入口保留为兼容链。平台装备修改事务会把每件装备的 `CHECKITEMW` 累加块同时写入旧重算和新运行时锚点。

**Tech Stack:** Python 3.12、unittest、UTF-8 JSON 成果包、GB18030 Mir 脚本、Tkinter/PyInstaller。

## Global Constraints

- 只支持当前翎风/LFM2 引擎。
- 不修改已验证有效的打怪伤害、切割、首尾斩杀和鞭尸逻辑。
- Mir 脚本保持 GB18030/CRLF；所有正式写入经平台事务备份、原子提交和回滚。
- 成果包不得执行任意 Python 或批处理。
- 当前服游戏内实效最终仍需用户复测，静态验证不得冒充游戏验证。

---

### Task 1: 运行时刷新成果包契约

**Files:**
- Create: `packages/verified/xy.combat.runtime-refresh/manifest.json`
- Modify: `tests/test_builtin_packages.py`

**Interfaces:**
- Consumes: `xy.combat.core` 提供的唯一 `AttackDamage` 标签。
- Produces: `XY_EQUIP_MAKER_RUNTIME_POWER_ANCHOR`、`...BLAST...`、`...DROP...`、`...DROP_MAX...`。

- [ ] **Step 1: Write the failing test**

在 `test_builtin_packages.py` 断言新包存在、依赖 core、只向 AttackDamage 写一个 event_hook，并包含四个锚点、100 基准、爆率封顶及三个最终命令。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_builtin_packages.BuiltinPackageTests.test_runtime_refresh_package_recalculates_failed_properties_on_attack`
Expected: FAIL，提示新 manifest 不存在。

- [ ] **Step 3: Write minimal implementation**

新增成果包 manifest；刷新块先初始化 `N$XY_RT_Power=100`、`N$XY_RT_Blast=100`、`N$XY_RT_Drop=100`、`N$XY_RT_DropMax=1000`，经过锚点累加、封顶后依次执行 `POWERRATE`、`SetBlastHitRate`、`KILLMONBURSTRATE`。

- [ ] **Step 4: Run test to verify it passes**

Run same test. Expected: PASS。

### Task 2: 装备属性双出口

**Files:**
- Modify: `做装备/profiles/script_properties.json`
- Modify: `做装备/tests/test_legacy_contract.py`
- Modify: `做装备/tests/test_equipment_transaction.py`

**Interfaces:**
- Consumes: Task 1 的四个锚点。
- Produces: 每件倍攻/爆伤/爆率/最大爆率装备的第二个 `CHECKITEMW` 五行受管块。

- [ ] **Step 1: Write the failing tests**

断言四种属性都同时拥有原重算 outlet 和 `runtime-*` outlet；隔离安装生成后 QFunction 中四个运行时变量分别由对应装备累加。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_legacy_contract tests.test_equipment_transaction`
Expected: FAIL，缺少 runtime outlets/anchors。

- [ ] **Step 3: Write minimal implementation**

为四项属性追加 runtime outlet，保持现有 marker、值、显示 BindType 和原实效出口不变。

- [ ] **Step 4: Run tests to verify they pass**

Run same modules. Expected: PASS。

### Task 3: 隔离服安装、升级和回滚

**Files:**
- Modify: `packages/verified/xy.combat.power/manifest.json`
- Modify: `packages/verified/xy.combat.blast/manifest.json`
- Modify: `packages/verified/xy.combat.drop/manifest.json`
- Test: `tests/test_planner_transaction.py`

**Interfaces:**
- Consumes: `xy.combat.runtime-refresh` 包 ID。
- Produces: 正确依赖排序，确保先有运行时锚点再插装备块。

- [ ] **Step 1: Write the failing test**

断言 power/blast/drop 依赖 runtime-refresh，并验证空白服组合预检、安装和逐字节回滚。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_planner_transaction`
Expected: FAIL，缺少新依赖。

- [ ] **Step 3: Write minimal implementation**

版本升为 1.1.0，并添加依赖；不改旧 managed block 内容。

- [ ] **Step 4: Run test to verify it passes**

Run same module. Expected: PASS。

### Task 4: 当前服事务部署与构建

**Files:**
- Modify transactionally: `D:/MirServer/Mir200/Envir/Market_Def/QFunction-0.txt`
- Build: `bin/XuanYuanDevPlatform.exe`, `bin/xydp-cli.exe`

**Interfaces:**
- Consumes: 新成果包、当前 `XuanYuanItems_Update.xlsx` 中装备行。
- Produces: 当前服 AttackDamage 运行时刷新块、四类装备累加分支和可回滚收据。

- [ ] **Step 1: Back up and preflight**

备份平台源文件和当前 QFunction；预检安装 runtime-refresh，再预检装备修改，要求 blockers 为空。

- [ ] **Step 2: Apply in transactions**

先安装 runtime-refresh，再用修改装备事务同步四类装备出口；记录两个事务号。

- [ ] **Step 3: Verify static contracts**

确认 AttackDamage 只有一个运行时 hook；四个锚点唯一；倍攻手镯、爆伤戒指、爆率头盔、爆率项链各自仅写入正确运行时变量；无 `????`；已有效属性脚本哈希/片段保持不变。

- [ ] **Step 4: Restart and build**

由 GameCenter 自动重启 M2，读取启动日志；运行 `build.ps1`，要求所有测试和双 EXE 构建 exit 0。

- [ ] **Step 5: Record handoff**

写独立交班记录并明确状态为 `待验证`，列出用户游戏内对照步骤。
