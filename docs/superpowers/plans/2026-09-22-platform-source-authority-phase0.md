# 玄渊平台源码权威化 Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `E:\XuanYuanDevPlatform` 中可维护的平台源码、安全地引入GitHub工作树的 `platform/` 镜像，并提供确定性的只读盘点、一次性引入和Git→运行副本三方预检能力。

**Architecture:** 复用现有仓库的 `tools/`，新增一个无第三方依赖的源码权威工具。策略文件明确允许的源目录、根文件、排除项和安全门；一次性引入只允许从E盘正式平台写入当前Git工作树，后续只读三方预检以初始快照为共同基线，区分Git修改、E盘漂移和真正冲突。本阶段不实现Git→E盘写入，不修改正式平台。

**Tech Stack:** Python 3.12、标准库 `argparse/dataclasses/hashlib/json/os/pathlib/re/shutil/tempfile/unittest`、PowerShell、Git。

**Spec:** `docs/superpowers/plans/2026-09-22-lfm2-asset-deployment-platform-roadmap.md`

## Global Constraints

- 只支持翎风/LFM2；正式平台根仍是 `E:\XuanYuanDevPlatform`。
- GitHub私有仓库保存源码、测试、Schema、功能卡和构建规则，不保存密码、数据库、完整客户端、`bin`、备份、构建缓存或大体积商业素材。
- 本阶段对E盘只读；任何Git→E盘应用、发布、`current-release.json`切换均不在范围内。
- 仅以高置信正则在文本类文件内检查硬编码密钥赋值；报告只输出路径和规则，不输出匹配值。相对路径/文件名命中同样阻断。
- 不跟随符号链接/目录联接；路径必须解析在指定来源根或目标镜像根内。
- 一次性引入不删除目标镜像文件；目标已有且哈希不同即阻断，不能静默覆盖。
- JSON输出UTF-8、稳定排序；文件内容逐字节复制，不改编码或换行。
- `packages`、`assets`、`library`、`bin`、`build`、`runtime`、`backups`、`evidence`、`outputs`、`workspace`不进入本阶段源码镜像。

## Review Focus

- 来源中出现junction/symlink：必须列入阻断且不遍历到根目录之外。
- 允许目录内出现疑似密钥文件名：必须阻断整个引入，不得只跳过后继续。
- 目标镜像已有不同内容：一次性引入必须阻断，不得覆盖Git工作。
- Git镜像与E盘从共同基线分别变化：预检必须报告冲突，不能选一方。
- E盘存在大量未管理文件：预检只比较快照管理集，不把运行数据误报成待删除。

---

### Task 1: 策略、只读盘点与安全门

**Files:**
- Create: `platform/source-authority.json`
- Create: `tools/platform_source_authority.py`
- Create: `tests/test_platform_source_authority.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `source-authority.json` 中的 `includeDirectories/rootFiles/excludeDirectoryNames/excludeSuffixes/sensitiveNamePatterns/maxFileBytes`。
- Produces: `load_policy(path: Path) -> SourcePolicy`；`inventory_source(source_root: Path, policy: SourcePolicy) -> dict[str, object]`；CLI `inventory`。

- [ ] **Step 1: 写策略加载与确定性盘点的失败测试**

测试建立真实临时目录，包含允许文件、`__pycache__/*.pyc`、未允许目录、超限文件、疑似 `.env` 文件和目录符号链接（Windows无权限创建链接时显式skip该用例）。断言允许文件按相对路径排序、SHA-256为手工字节值、排除项不进入文件清单、超限/敏感名/链接进入 `blockers`，且两次盘点的 `sourceFingerprint` 相同。

```python
class InventoryTests(unittest.TestCase):
    def test_inventory_is_deterministic_and_blocks_unsafe_entries(self):
        source = self.make_source_tree()
        report = inventory_source(source, load_policy(self.policy_path))
        self.assertEqual([f["path"] for f in report["files"]], ["README.md", "src/xydp/app.py"])
        self.assertEqual(report["files"][1]["sha256"], hashlib.sha256(b"print('ok')\n").hexdigest())
        self.assertEqual(report["sourceFingerprint"], inventory_source(source, load_policy(self.policy_path))["sourceFingerprint"])
        self.assertEqual({b["code"] for b in report["blockers"]}, {"sensitive-name", "file-too-large", "reparse-point"})
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m unittest tests.test_platform_source_authority.InventoryTests -v`

Expected: FAIL，`tools.platform_source_authority` 或接口尚不存在。

- [ ] **Step 3: 实现最小策略和盘点器**

实现不可变 `SourcePolicy`，严格验证策略字段、相对路径和正整数上限。盘点器按允许根枚举普通文件，拒绝reparse point，逐文件计算大小/SHA-256，文件清单排序后用规范JSON计算总指纹；报告字段固定为：

```python
{
    "schemaVersion": 1,
    "sourceRoot": str(source_root.resolve()),
    "sourceFingerprint": "...",
    "summary": {"managedFiles": 0, "managedBytes": 0, "blockers": 0},
    "files": [{"path": "src/xydp/app.py", "bytes": 12, "sha256": "..."}],
    "blockers": [{"code": "sensitive-name", "path": "tests/.env", "message": "..."}],
}
```

策略首版管理：`src`、`tests`、`tools`、`做装备/src`、`做装备/tests`、`接口`、`docs`、`templates`；根文件只允许 `README.md`、`AGENTS.md`、`.gitignore`、`build.ps1`、`run_cli.py`、`run_gui.py`、`Start_XuanYuanDevPlatform.bat`。排除缓存、编译产物、日志和临时目录；单文件上限2 MiB。

CLI：

```powershell
python tools/platform_source_authority.py inventory `
  --source-root E:\XuanYuanDevPlatform `
  --policy platform/source-authority.json `
  --output D:\codex临时工作区\MY-PAK-MIGRATION-20260922\platform-source-inventory.json
```

有blocker时退出码2，无blocker时0；输出文件使用临时文件+`os.replace`。

- [ ] **Step 4: 运行测试并补充真实CLI行为测试**

新增subprocess测试，断言无blocker返回0、报告可解析；疑似敏感名返回2，且来源文件的mtime/hash不变。

Run: `python -m unittest tests.test_platform_source_authority.InventoryTests -v`

Expected: PASS。

- [ ] **Step 5: 提交Task 1**

```powershell
git add .gitignore platform/source-authority.json tools/platform_source_authority.py tests/test_platform_source_authority.py
git commit -m "feat: add platform source inventory policy"
```

### Task 2: 一次性安全引入到Git镜像

**Files:**
- Modify: `tools/platform_source_authority.py`
- Modify: `tests/test_platform_source_authority.py`

**Interfaces:**
- Consumes: Task 1 `inventory_source()` 的无阻断报告。
- Produces: `plan_bootstrap(source_root: Path, mirror_root: Path, policy: SourcePolicy) -> dict[str, object]`；`apply_bootstrap(plan: dict[str, object], *, confirmed: bool) -> dict[str, object]`；CLI `bootstrap-plan/bootstrap-apply`。

- [ ] **Step 1: 写一次性引入计划和覆盖保护的失败测试**

测试断言：空镜像得到两条`create`；同哈希文件为`unchanged`；不同哈希文件产生 `destination-conflict` blocker；`confirmed=False`拒绝应用；无阻断确认应用后目标字节、SHA和mtime与来源一致；重复计划为noop且不改mtime。

```python
def test_bootstrap_refuses_to_overwrite_different_destination(self):
    (self.mirror / "src/xydp").mkdir(parents=True)
    (self.mirror / "src/xydp/app.py").write_bytes(b"git work\n")
    plan = plan_bootstrap(self.source, self.mirror, self.policy)
    self.assertEqual(plan["blockers"][0]["code"], "destination-conflict")
    with self.assertRaises(SourceAuthorityError):
        apply_bootstrap(plan, confirmed=True)
    self.assertEqual((self.mirror / "src/xydp/app.py").read_bytes(), b"git work\n")
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m unittest tests.test_platform_source_authority.BootstrapTests -v`

Expected: FAIL，bootstrap接口尚不存在。

- [ ] **Step 3: 实现计划、确认门和原子复制**

计划字段固定包含：`schemaVersion/mode/sourceRoot/mirrorRoot/sourceFingerprint/changes/blockers/isNoop`。每条change包含 `path/action/sourceSha256/destinationSha256`。应用时重新盘点并验证计划指纹，任何漂移在首个写入前停止；逐文件复制到同目录唯一临时文件，用原子不覆盖硬链接提交并回读SHA，若目标在复制期间出现则保留对方文件并停止。禁止delete和update，只有`create/unchanged`。

应用完成后在镜像根写 `source-authority.snapshot.json`，记录共同基线文件哈希与来源根；该元数据不属于E盘镜像文件集。

- [ ] **Step 4: 运行Task 2与Task 1测试**

Run: `python -m unittest tests.test_platform_source_authority -v`

Expected: PASS，且测试临时目录外无写入。

- [ ] **Step 5: 提交Task 2**

```powershell
git add tools/platform_source_authority.py tests/test_platform_source_authority.py
git commit -m "feat: add guarded platform source bootstrap"
```

### Task 3: Git到E盘运行副本的三方只读预检

**Files:**
- Modify: `tools/platform_source_authority.py`
- Modify: `tests/test_platform_source_authority.py`

**Interfaces:**
- Consumes: Task 2 `source-authority.snapshot.json` 共同基线。
- Produces: `preflight_sync(mirror_root: Path, runtime_root: Path, snapshot_path: Path) -> dict[str, object]`；CLI `sync-preflight`。

- [ ] **Step 1: 写三方状态矩阵失败测试**

用手工字节构造以下状态并断言：

| Git镜像 | E盘运行副本 | 预期 |
|---|---|---|
| 等于基线 | 等于基线 | `unchanged` |
| 已修改 | 等于基线 | `update-runtime` |
| 等于基线 | 已修改 | blocker `runtime-drift` |
| 两边同改且字节相同 | 相同 | `converged` |
| 两边分别修改 | 不同 | blocker `three-way-conflict` |
| Git存在、运行副本缺失 | 缺失 | `create-runtime` |
| Git缺失、运行副本存在 | 存在 | blocker `mirror-missing` |

同时在运行副本放一个未进入快照的 `bin/large.exe`，断言不出现在changes或blockers中。

- [ ] **Step 2: 运行失败测试**

Run: `python -m unittest tests.test_platform_source_authority.SyncPreflightTests -v`

Expected: FAIL，`preflight_sync`尚不存在。

- [ ] **Step 3: 实现只读三方预检**

只遍历快照的管理路径，对三份哈希（baseline、mirror、runtime）分类。报告字段固定：`schemaVersion/mode/mirrorRoot/runtimeRoot/snapshotFingerprint/changes/blockers/isNoop`。不提供 `sync-apply` 子命令；任何代码路径都不得写runtimeRoot。

- [ ] **Step 4: 验证预检零写入**

测试调用前后递归记录运行副本路径、字节、mtime，断言完全相同；运行全文件测试。

Run: `python -m unittest tests.test_platform_source_authority -v`

Expected: PASS。

- [ ] **Step 5: 提交Task 3**

```powershell
git add tools/platform_source_authority.py tests/test_platform_source_authority.py
git commit -m "feat: add read-only platform source sync preflight"
```

### Task 4: 真实E盘盘点、镜像引入和候选验证

**Files:**
- Create: `platform/src/**`
- Create: `platform/tests/**`
- Create: `platform/tools/**`
- Create: `platform/做装备/src/**`
- Create: `platform/做装备/tests/**`
- Create: `platform/接口/**`
- Create: `platform/docs/**`
- Create: `platform/templates/**`
- Create: `platform/source-authority.snapshot.json`
- Create: `docs/superpowers/plans/2026-09-22-lfm2-asset-deployment-platform-roadmap.md`
- Modify: `D:\codex临时工作区\MY-PAK-MIGRATION-20260922\progress.md`（只追加本阶段结果，不纳入Git提交）

**Interfaces:**
- Consumes: Tasks 1–3 CLI；只读来源 `E:\XuanYuanDevPlatform`。
- Produces: Git可审查源码镜像、真实盘点报告、真实sync-preflight报告和提交。

- [ ] **Step 1: 对正式平台运行只读盘点**

Run:

```powershell
python tools/platform_source_authority.py inventory `
  --source-root E:\XuanYuanDevPlatform `
  --policy platform/source-authority.json `
  --output D:\codex临时工作区\MY-PAK-MIGRATION-20260922\platform-source-inventory.json
```

Expected: exit 0、`blockers=[]`；若出现blocker，停止引入，记录具体路径并修正策略或排除敏感源，不能绕过。

- [ ] **Step 2: 生成并审阅一次性引入计划**

Run:

```powershell
python tools/platform_source_authority.py bootstrap-plan `
  --source-root E:\XuanYuanDevPlatform `
  --mirror-root platform `
  --policy platform/source-authority.json `
  --output D:\codex临时工作区\MY-PAK-MIGRATION-20260922\platform-bootstrap-plan.json
```

Expected: 只有`create/unchanged`，零`update/delete`，零blocker；总文件和总字节与inventory一致。

- [ ] **Step 3: 确认应用到隔离Git工作树**

Run:

```powershell
python tools/platform_source_authority.py bootstrap-apply `
  --plan D:\codex临时工作区\MY-PAK-MIGRATION-20260922\platform-bootstrap-plan.json `
  --policy platform/source-authority.json --yes
```

Expected: 仅写当前工作树的 `platform/`；回读全部SHA匹配；E盘来源根指纹和mtime不变。

- [ ] **Step 4: 运行真实三方预检**

Run:

```powershell
python tools/platform_source_authority.py sync-preflight `
  --mirror-root platform `
  --runtime-root E:\XuanYuanDevPlatform `
  --snapshot platform/source-authority.snapshot.json `
  --output D:\codex临时工作区\MY-PAK-MIGRATION-20260922\platform-sync-preflight.json
```

Expected: `blockers=[]`；除安全复核明确脱敏的文件为`update-runtime`外，其余管理项均为`unchanged`，且E盘目录树前后指纹不变。本阶段不执行该更新。

- [ ] **Step 5: 验证镜像可导入和测试**

Run:

```powershell
python -m compileall -q platform\src platform\做装备\src
$env:PYTHONPATH="$PWD\platform\src;$PWD\platform\做装备\src"
python -m unittest tests.test_platform_source_authority -v
```

Expected: compileall exit 0；本功能测试全部PASS。完整平台套件在后续“外部运行数据依赖拆分”阶段执行，本阶段不把缺失packages/assets误报为源码错误。

- [ ] **Step 6: 安全复核与提交**

Run:

```powershell
git status --short
git diff --check
git grep -n -I -E "(api[_-]?key|password|passwd|token|BEGIN (RSA |OPENSSH )?PRIVATE KEY)" -- platform
```

Expected: 仅计划内文件；`diff --check`零错误；敏感扫描零命中或每个命中均为无秘密的字段名/测试字面量并记录裁定。

```powershell
git add .gitignore docs/superpowers/plans platform tools/platform_source_authority.py tests/test_platform_source_authority.py
git commit -m "feat: establish platform source authority candidate"
```

本提交只表示“Git源码候选+只读预检通过”，不表示已发布、已同步E盘或已游戏验收。
