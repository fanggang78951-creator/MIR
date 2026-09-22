# Monster Library V3 Engine Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有按Appr猜补丁的怪物库V2升级为遵循翎风/LFM2引擎规则的V3闭包平台，使普通怪物和SmartMonster自定义怪物都能安全扫描、生成、事务植入和回滚。

**Architecture:** 新增纯函数引擎解析层、V3目录层、SmartMonster目标规划层和登录器验收层；现有`MonsterLibraryService`继续作为总编排和事务入口，现有表格与GUI只消费V3状态，不自行猜资源。普通Appr路径保留并回归，SmartMonster路径以同名INI、EffectImageList零基引用和多资源依赖为闭包。

**Tech Stack:** Python 3.12、标准库`sqlite3/configparser/hashlib/pathlib/unittest`、openpyxl、Tkinter、PowerShell 7、PyInstaller、GB18030/CRLF翎风文本合同。

**Spec:** `E:\XuanYuanDevPlatform\docs\superpowers\specs\2026-08-23-monster-library-v3-engine-closure-design.md`

## Global Constraints

- 平台根目录固定为`E:\XuanYuanDevPlatform`；目标服务端默认`D:\MirServer`，目标客户端data默认`E:\11周年\data`。
- 平台目录当前不是Git仓库，不得把平台代码提交到`C:\Users\Administrator\Documents\做传奇`的无关Git仓库。
- 执行前备份本计划列出的既有源码、测试、模板、接口和打包文件到`E:\XuanYuanDevPlatform\backups\monster-library-v3\<timestamp>\source-before`；最终验收和交班完成后清理临时备份。
- 每项任务使用“RED失败测试→最小实现→GREEN通过→相邻回归→哈希检查点”，不使用虚假的git commit步骤。
- 所有正式端写入默认禁止；Task 1至Task 10只使用临时目录和隔离夹具。用户另行确认前不写`D:\MirServer`、`E:\11周年`或MakeGameLogin配置。
- 不打开、关闭或操作M2、GameCenter和游戏客户端；不新增MonGen，不修改爆率、地图、NPC、任务或AI。
- 翎风文本保持原编码、BOM和换行；EffectImageList不得重排或规范化历史行。
- SmartMonster资源号按EffectImageList零基解释；目标端必须重新分配，禁止复制供体数字。
- 新怪只使用用户基础属性、目标中性模板和引擎模型白名单字段；禁止继承供体血量、攻击、防御、经验和特殊能力。
- 默认随机池只包含`ready_verified`；`ready_opaque`只能显式选择，`incomplete/complex_ability/conflict/unsupported`不得植入。
- 复杂攻击、召唤、附加状态和保护能力第一版直接跳过，不尝试自动删改供体能力。
- SmartMonster变更后状态必须为“待自定义怪物DAT与登录器集成”，不得仅因静态部署成功宣称游戏可用。
- 星辰怪13是黄金样本；通用实现不得依赖`SOURCE_MONSTER`、`TARGET_MONSTER`或固定资源号常量。

## File Map

### New focused modules

- `src/xydp/monster_engine.py`：引擎模式分类、EffectImageList精确解析、SmartMonster INI依赖收集、能力门禁、动作帧验证和INI重写。
- `src/xydp/monster_catalog_v3.py`：V3记录类型、SQLite schema、原子重建、V2识别和依赖查询。
- `src/xydp/monster_smart_transaction.py`：目标零基分配、独立资源命名、多怪批量候选和SmartMonster生成文件计划。
- `src/xydp/monster_login_integration.py`：MakeGameLogin配置读取、DAT/登录器时间门禁和用户动作摘要。
- `tests/monster_v3_fixtures.py`：自包含SQLite、INI、EffectImageList和最小WZL/WZX夹具生成器。

### Existing files to modify

- `src/xydp/monster_library.py:53-158,486-749,751-896,898-1368`：接入V3目录、扫描、闭包计划、事务负载和回执。
- `src/xydp/monster_workbook.py:30-107,313-365,408-543`：基础属性与模型字段分离、稳定随机候选池和显式opaque规则。
- `src/xydp/gui.py:830-920,1429-1653`：V3扫描入口、列表列项、状态筛选、预检摘要和登录器门禁提示。
- `src/xydp/cli.py:174-199,550-579`：供体服务端根目录覆盖、V3扫描/验收命令和JSON输出。
- `tests/test_monster_library.py`：普通Appr回归、V3扫描和事务回归。
- `tests/test_monster_workbook.py`：属性隔离、随机池、已有怪保模和opaque显式选择。
- `tests/test_monster_gui_default_paths.py`：E盘默认路径及V3界面文字门禁。
- `tests/test_deploy_star_monster13_smartmonster.py`：保留专用工具历史回归，并新增“通用解析结果等价”断言。
- `README.md`：V3使用边界和人工DAT步骤。
- `接口/30_星辰怪首饰店一键生成接口.txt`：将星辰怪13标记为已游戏验收，登记通用V3入口并废弃专用脚本作为默认路线。
- `bin/玄渊成果平台使用手册/Codex维护记录/生成工具/build_illustrated_manual.py:427-440,481-499`：更新怪物库页面说明。

### New tests

- `tests/test_monster_engine.py`
- `tests/test_monster_catalog_v3.py`
- `tests/test_monster_smart_transaction.py`
- `tests/test_monster_login_integration.py`

---

### Task 1: 自包含黄金夹具与纯引擎解析器

**Files:**
- Create: `E:\XuanYuanDevPlatform\tests\monster_v3_fixtures.py`
- Create: `E:\XuanYuanDevPlatform\tests\test_monster_engine.py`
- Create: `E:\XuanYuanDevPlatform\src\xydp\monster_engine.py`
- Test: `E:\XuanYuanDevPlatform\tests\test_deploy_star_monster13_smartmonster.py`

**Interfaces:**
- Produces: `EngineDependency`, `MonsterEngineClosure`, `EffectImageListDocument` dataclasses.
- Produces: `derive_donor_server_root(database: Path) -> Path`.
- Produces: `classify_engine_mode(monster_values: Mapping[str, object], smart_ini: Path | None) -> str`.
- Produces: `parse_effect_image_list(path: Path) -> EffectImageListDocument`.
- Produces: `build_smartmonster_closure(monster_values: Mapping[str, object], smart_ini: Path, effect_list: Path, client_roots: Sequence[Path], pak_passwords: Mapping[str, set[str]]) -> MonsterEngineClosure`.
- Produces: `rewrite_smartmonster_ini(ini_bytes: bytes, source_to_target: Mapping[int, int]) -> bytes`.

- [ ] **Step 1: 建立最小WZL/WZX与星辰怪13等价夹具**

在`tests/monster_v3_fixtures.py`提供以下可复用接口，生成的WZX保留1700项，只有站、走、攻、伤、死实际播放索引写入type259帧：

```python
STAR13_ACTIONS = {
    "ActStand": (1340, 4, 6, 1),
    "ActWalk": (1420, 6, 4, 1),
    "ActStruck": (1580, 2, 0, 1),
    "ActDie": (1600, 10, 0, 1),
    "ActAttack1": (1500, 6, 4, 1),
}

def write_wzl_wzx_pair(root: Path, stem: str, actions=STAR13_ACTIONS,
                       frame_type: int = 259) -> tuple[Path, Path]: ...

def write_smartmonster_ini(path: Path, resource_index: int = 78,
                           *, extra_attack: bool = False) -> Path: ...

def write_effect_image_list(path: Path, entries: list[str]) -> Path: ...
```

- [ ] **Step 2: 写引擎解析失败测试**

```python
def test_star13_equivalent_closure_collects_all_zero_based_dependencies(self):
    closure = build_smartmonster_closure(...)
    self.assertEqual(closure.engine_mode, "smartmonster")
    self.assertEqual(closure.closure_status, "ready_verified")
    self.assertEqual(closure.total_verified_play_frames, 224)
    self.assertEqual(closure.resource_reference_counts, {"ActionFile": 12, "EffectFile": 1})

def test_raceimg156_without_same_name_ini_is_incomplete(self): ...
def test_zero_based_78_resolves_physical_line_79(self): ...
def test_complex_server_attack_is_not_random_ready(self): ...
def test_rewrite_changes_every_non_negative_resource_reference(self): ...
```

- [ ] **Step 3: 运行RED并保存失败证据**

Run:

```powershell
Set-Location 'E:\XuanYuanDevPlatform'
$env:PYTHONPATH='E:\XuanYuanDevPlatform\src'
py -3 -m unittest tests.test_monster_engine -v
```

Expected: FAIL，首个错误为`ModuleNotFoundError: No module named 'xydp.monster_engine'`。

- [ ] **Step 4: 实现纯解析器最小数据合同**

`monster_engine.py`先实现不可变记录和资源键白名单：

```python
RESOURCE_KEYS = frozenset({
    "HPFile", "ActionFile", "EffectFile", "EffectFile2", "Fly_File",
    "FlyEff_File", "Self_File", "SelfKeep_File", "Explosion_File", "Target_File",
})
ALLOWED_MONSTER_FRAME_TYPES = frozenset({259, 261})

@dataclass(frozen=True)
class EngineDependency:
    source_index: int
    entry: str
    kind: str
    source_path: str
    companion_path: str | None
    source_hash: str
    companion_hash: str | None
    pak_password: str | None

@dataclass(frozen=True)
class MonsterEngineClosure:
    engine_mode: str
    closure_status: str
    closure_hash: str
    smart_ini_path: str | None
    smart_ini_hash: str | None
    dependencies: tuple[EngineDependency, ...]
    resource_reference_counts: dict[str, int]
    total_verified_play_frames: int
    login_policy: str
    capability_policy: str
    reason: str | None
```

- [ ] **Step 5: 实现精确零基解析、能力门禁和帧验证**

要求`parse_effect_image_list`保留原始bytes、编码、BOM、换行和每个物理行；引用空行时报错，不删除空行。将星辰怪13专用工具中已验证的`detect_text`、能力检查、动作索引算法泛化，不保留固定怪物名、固定78或固定Mon7常量。

- [ ] **Step 6: 运行GREEN与历史等价测试**

Run:

```powershell
py -3 -m unittest tests.test_monster_engine tests.test_deploy_star_monster13_smartmonster -v
```

Expected: 所有测试PASS；通用夹具报告13处重写和224帧。

- [ ] **Step 7: 记录Task 1哈希检查点**

Run:

```powershell
Get-FileHash 'src\xydp\monster_engine.py','tests\monster_v3_fixtures.py','tests\test_monster_engine.py' -Algorithm SHA256
```

Expected: 三个文件均存在且哈希非空；将结果保存到`E:\XuanYuanDevPlatform\evidence\monster-library-v3\task-01.json`。

---

### Task 2: V3目录Schema与V2拒绝门禁

**Files:**
- Create: `E:\XuanYuanDevPlatform\src\xydp\monster_catalog_v3.py`
- Create: `E:\XuanYuanDevPlatform\tests\test_monster_catalog_v3.py`
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_library.py:53-175,751-793`
- Test: `E:\XuanYuanDevPlatform\tests\test_monster_library.py`

**Interfaces:**
- Consumes: `MonsterEngineClosure` and `EngineDependency` from Task 1.
- Produces: `MonsterRecord` with V3 engine fields and backward-compatible properties.
- Produces: `MonsterDependencyRecord`.
- Produces: `CatalogV3Repository.rebuild(...)`, `.list_monsters(...)`, `.dependencies_for(monster_id)`.
- Re-exports: `MonsterRecord` from `xydp.monster_library` so existing imports continue working.

- [ ] **Step 1: 写V3 schema失败测试**

```python
def test_v3_catalog_persists_multiple_dependencies_and_engine_fields(self): ...
def test_v2_catalog_is_rejected_instead_of_guessed(self):
    with self.assertRaisesRegex(MonsterLibraryError, "V2.*重建V3"):
        repository.open()
def test_preview_state_does_not_change_closure_status(self): ...
```

- [ ] **Step 2: 运行RED**

Run: `py -3 -m unittest tests.test_monster_catalog_v3 -v`  
Expected: FAIL，缺少`xydp.monster_catalog_v3`。

- [ ] **Step 3: 实现V3记录与SQLite schema**

核心表必须显式包含：

```sql
CREATE TABLE monsters (
  monster_id INTEGER PRIMARY KEY,
  monster_name TEXT NOT NULL,
  monster_json TEXT NOT NULL,
  engine_mode TEXT NOT NULL,
  closure_status TEXT NOT NULL,
  closure_hash TEXT NOT NULL,
  smart_ini_path TEXT,
  smart_ini_hash TEXT,
  source_effect_list_path TEXT,
  source_effect_list_hash TEXT,
  resource_manifest_json TEXT NOT NULL,
  login_policy TEXT NOT NULL,
  capability_policy TEXT NOT NULL,
  preview_path TEXT,
  preview_state TEXT NOT NULL,
  skip_reason TEXT
);
CREATE TABLE monster_dependencies (
  monster_id INTEGER NOT NULL,
  ordinal INTEGER NOT NULL,
  source_index INTEGER NOT NULL,
  entry TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_path TEXT NOT NULL,
  companion_path TEXT,
  source_hash TEXT NOT NULL,
  companion_hash TEXT,
  pak_password TEXT,
  PRIMARY KEY(monster_id, ordinal)
);
```

保留V2现有展示和Monster字段列，`meta.schema_version`固定为`3`。

- [ ] **Step 4: 实现原子重建与V2门禁**

先写`catalog.sqlite.staging-<uuid>`，执行`PRAGMA integrity_check`后`os.replace`；检测到旧表无`engine_mode`或meta版本不是3时，抛出明确错误，不原地ALTER猜数据。

- [ ] **Step 5: 兼容现有服务接口**

`MonsterRecord`继续提供`monster_values`属性；`list_monsters("ready")`映射为`closure_status='ready_verified'`，旧GUI尚未修改前不崩溃。

- [ ] **Step 6: 运行GREEN与V2回归**

Run:

```powershell
py -3 -m unittest tests.test_monster_catalog_v3 tests.test_monster_library -v
```

Expected: V3新测试PASS；V2测试中只允许“旧schema现在明确阻止”的断言按新文案更新，不允许放宽资源冲突测试。

- [ ] **Step 7: 记录Task 2检查点**

保存schema SQL、测试计数和`PRAGMA integrity_check=ok`到`evidence\monster-library-v3\task-02.json`。

---

### Task 3: 按引擎规则扫描供体并构建V3闭包

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_library.py:486-749,795-896`
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_catalog_v3.py`
- Modify: `E:\XuanYuanDevPlatform\tests\test_monster_library.py`
- Modify: `E:\XuanYuanDevPlatform\tests\test_monster_engine.py`

**Interfaces:**
- Consumes: Task 1 parser and Task 2 repository.
- Produces: `MonsterLibraryService.scan(..., donor_server_root: Path | None = None) -> CatalogScanResult`.
- Produces metadata key `donor_server_root` and scan counts by engine/status.

- [ ] **Step 1: 写扫描分流失败测试**

```python
def test_scan_routes_standard_and_smartmonster_through_different_parsers(self): ...
def test_scan_derives_server_root_from_mud2_db_path(self): ...
def test_raceimg156_missing_ini_is_incomplete_not_ready(self): ...
def test_smartmonster_localizes_ini_and_every_dependency_by_hash(self): ...
def test_complex_ability_is_excluded_from_default_random_pool(self): ...
```

- [ ] **Step 2: 运行RED**

Run: `py -3 -m unittest tests.test_monster_library.MonsterLibraryTests -v`  
Expected: FAIL，因为`scan`仍统一执行`appr_to_library`且catalog schema仍缺V3闭包数据。

- [ ] **Step 3: 扩展scan签名且保持旧调用兼容**

```python
def scan(self, donor_database, donor_wzl_data, donor_pak_data, donor_pak_rules,
         target_server, target_client_data, *, donor_server_root=None,
         materialize=True) -> CatalogScanResult:
    resolved_donor_root = (
        Path(donor_server_root).resolve()
        if donor_server_root else derive_donor_server_root(Path(donor_database))
    )
```

验证`resolved_donor_root/Mir200/Envir/EffectImageList.txt`和`!setup.txt`，但普通Appr扫描不能因SmartMonster目录为空而整体失败。

- [ ] **Step 4: 实现逐怪分类与本地化**

普通怪保留V2资源冲突逻辑；SmartMonster调用Task 1闭包解析器，将INI保存到`怪物库/assets/smartmonster/<closure-hash>/`，依赖按源哈希复用，不重复复制大文件。

- [ ] **Step 5: 写V3目录并报告分类计数**

`CatalogScanResult`新增`standard_appr`、`smartmonster`、`ready_verified`、`ready_opaque`、`incomplete`、`complex_ability`计数；保留旧字段供界面过渡。

- [ ] **Step 6: 运行GREEN和黄金等价测试**

Run:

```powershell
py -3 -m unittest tests.test_monster_engine tests.test_monster_catalog_v3 tests.test_monster_library tests.test_deploy_star_monster13_smartmonster -v
```

Expected: 全部PASS；通用扫描所得星辰怪13闭包与专用工具在零基号、13处引用和224帧上等价。

- [ ] **Step 7: 验证只读边界**

在临时供体/目标夹具扫描前后比较供体DB、EffectImageList、INI、资源和目标DB哈希；Expected: 全部不变，仅平台临时catalog/assets新增。

---

### Task 4: SmartMonster目标候选和零基重定位

**Files:**
- Create: `E:\XuanYuanDevPlatform\src\xydp\monster_smart_transaction.py`
- Create: `E:\XuanYuanDevPlatform\tests\test_monster_smart_transaction.py`
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_library.py:120-158,898-1238`

**Interfaces:**
- Consumes: V3 `MonsterRecord` and dependency records.
- Produces: `SmartGeneratedFile(target_path: str, content: bytes, after_hash: str)`.
- Produces: `SmartMonsterBatchPlan(effect_list_after: bytes, generated_files: tuple[SmartGeneratedFile, ...], resource_mappings: tuple[dict[str, object], ...], blockers: tuple[str, ...])`.
- Produces: `build_smartmonster_batch(records, dependencies, server_root, client_data) -> SmartMonsterBatchPlan`.

- [ ] **Step 1: 写目标规划失败测试**

```python
def test_batch_allocates_zero_based_indices_without_reordering_history(self): ...
def test_multiple_source_indices_are_all_rewritten(self): ...
def test_same_hash_dependency_is_reused_safely(self): ...
def test_same_name_different_hash_gets_independent_xy_name(self): ...
def test_partial_existing_target_is_blocker(self): ...
def test_effect_list_drift_invalidates_plan(self): ...
```

- [ ] **Step 2: 运行RED**

Run: `py -3 -m unittest tests.test_monster_smart_transaction -v`  
Expected: FAIL，缺少模块。

- [ ] **Step 3: 实现稳定独立资源命名**

```python
def target_resource_entry(monster_id: int, ordinal: int, source: EngineDependency) -> str:
    suffix = Path(source.entry).suffix.lower()
    return f"XY_MonV3_{monster_id}_{ordinal}_{source.source_hash[:8]}{suffix}"
```

同一目标文件名存在且哈希一致时复用；存在且哈希不同则阻止，不覆盖。

- [ ] **Step 4: 实现批量零基分配和INI生成**

按当前EffectImageList物理行数分配新索引；同一批多个怪物共享同哈希依赖时只追加一次。每只目标INI使用目标怪物名，并调用Task 1重写器验证无源编号残留。

- [ ] **Step 5: 将生成内容挂入MonsterLibraryPlan**

给`MonsterLibraryPlan`新增：

```python
generated_files_after: dict[str, bytes] = field(default_factory=dict)
engine_assignments: tuple[dict[str, object], ...] = ()
requires_custom_monster_dat: bool = False
requires_login_regeneration: bool = False
```

计划只保存候选bytes和哈希，不在预检时写生产端。

- [ ] **Step 6: 运行GREEN**

Run: `py -3 -m unittest tests.test_monster_smart_transaction -v`  
Expected: 全部PASS；EffectImageList历史前缀逐字节不变，新增条目只有预期独立资源。

- [ ] **Step 7: 运行多怪幂等预检**

同一输入连续调用两次`build_smartmonster_batch`，Expected: 目标资源名、目标零基号、INI bytes和计划摘要完全相同。

---

### Task 5: 将SmartMonster闭包纳入现有事务、回读和回滚

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_library.py:898-1368`
- Modify: `E:\XuanYuanDevPlatform\tests\test_monster_library.py`
- Modify: `E:\XuanYuanDevPlatform\tests\test_monster_smart_transaction.py`

**Interfaces:**
- Consumes: `SmartMonsterBatchPlan` from Task 4.
- Produces change kinds: `smart-generated-file` and `effect-image-list`.
- Extends receipt with `engine_assignments`, `requires_custom_monster_dat`, `requires_login_regeneration`.

- [ ] **Step 1: 写事务失败与回滚测试**

```python
def test_install_commits_db_ini_resources_and_effect_list_in_one_transaction(self): ...
def test_failure_after_second_generated_file_restores_every_prior_target(self): ...
def test_rollback_refuses_when_effect_list_changed_after_install(self): ...
def test_database_and_mongen_are_unchanged_when_only_model_closure_is_added(self): ...
def test_repeated_preflight_reports_already_deployed(self): ...
```

- [ ] **Step 2: 运行RED**

Run: `py -3 -m unittest tests.test_monster_library -v`  
Expected: 新测试FAIL，因为`install`尚不认识SmartMonster生成内容。

- [ ] **Step 3: 预检合并SmartMonster批次计划**

`MonsterLibraryService.preflight`在普通资源计划后收集`engine_mode='smartmonster'`记录，调用Task 4；blocker合并后才构建数据库bytes，确保闭包失败时数据库不进入可提交状态。

- [ ] **Step 4: 扩展install写入分支**

```python
elif change.kind in {"smart-generated-file", "effect-image-list"}:
    payload = plan.generated_files_after.get(str(target))
    if payload is None:
        raise MonsterLibraryError(f"计划缺少生成内容：{target}")
    _atomic_write(target, payload)
```

仍使用现有统一备份metadata和反向回滚，不另建第二套事务系统。

- [ ] **Step 5: 加入提交后闭包回读**

重新读取目标EffectImageList、同名INI和资源哈希；再次解析目标INI，确认每个目标资源号解析到计划条目。数据库、MonGen和未涉及公共资源的哈希必须符合计划。

- [ ] **Step 6: 运行GREEN与故障注入测试**

Run:

```powershell
py -3 -m unittest tests.test_monster_library tests.test_monster_smart_transaction -v
```

Expected: 提交、already-deployed、故障回滚和回滚漂移阻止全部PASS。

- [ ] **Step 7: 隔离完整事务演练**

在`怪物库/simulation/v3-engine-closure-transaction`执行`ready -> deployed -> already-deployed -> rolled-back -> ready`；Expected: 回滚后隔离目标逐文件哈希等于演练前，正式端哈希不变。

---

### Task 6: 表格基础属性与模型闭包彻底分离

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_workbook.py:30-107,313-406,408-543`
- Modify: `E:\XuanYuanDevPlatform\tests\test_monster_workbook.py`
- Test: `E:\XuanYuanDevPlatform\tests\test_monster_library.py`

**Interfaces:**
- Consumes: V3 closure statuses and transaction planner.
- Produces: `_compose_new_monster_values(spec, neutral_values, model_values) -> dict[str, object]`.
- Uses fixed `MODEL_FIELD_ALLOWLIST` and existing `FIELD_BY_HEADER` user overrides.

- [ ] **Step 1: 写供体属性泄漏失败测试**

```python
def test_new_monster_uses_target_neutral_defaults_not_donor_stats(self):
    values = service._compose_new_monster_values(spec, neutral, donor)
    self.assertEqual(values["HP"], spec_hp)
    self.assertEqual(values["DC"], spec_dc)
    self.assertEqual(values["RaceImg"], donor["RaceImg"])
    self.assertNotEqual(values["ExploreItem"], donor["ExploreItem"])

def test_blank_model_uses_only_ready_verified_pool(self): ...
def test_ready_opaque_requires_explicit_model_id(self): ...
def test_existing_monster_blank_model_preserves_current_model(self): ...
```

- [ ] **Step 2: 运行RED**

Run: `py -3 -m unittest tests.test_monster_workbook -v`  
Expected: 属性泄漏测试FAIL，因为当前`_custom_record`先复制供体整行。

- [ ] **Step 3: 定义明确字段白名单**

```python
MODEL_FIELD_ALLOWLIST = {
    "Race", "RaceImg", "Appr", "SPEED", "WalkStep", "WalkWait",
    "AttackState", "AttackSource", "DisableSimpleActor",
}
NEUTRAL_TEMPLATE_NAME = "稻草人"
```

`WALK_SPD`、`ATTACK_SPD`优先使用表格值；表格未提供时使用目标中性模板，而不是供体。

- [ ] **Step 4: 实现新怪合成顺序**

```python
values = dict(neutral_values)
values["Name"] = spec.name
for field in MODEL_FIELD_ALLOWLIST:
    values[field] = model_values[field]
values.update(dict(spec.overrides))
```

目标端找不到唯一“稻草人”时阻止新增怪，并给出精确错误；更新已有怪不受影响。

- [ ] **Step 5: 调整候选池与显式选择**

`ready_verified`进入自动池；显式`模型库编号`可选`ready_verified/ready_opaque`，后者写入警告和单怪验收要求；其他状态直接阻止。

- [ ] **Step 6: 运行GREEN与表格回归**

Run:

```powershell
py -3 -m unittest tests.test_monster_workbook tests.test_monster_library -v
```

Expected: 基础属性、名称颜色、稳定随机、已有怪保模和不新增MonGen全部PASS。

- [ ] **Step 7: 复核正式模板列**

读取`所需材料表格汇总\20_怪物批量生成.xlsx`，Expected: 用户必填列不增加；`模型Appr`如存在只保留兼容，不新增PAK、INI、资源号或客户端路径列。

---

### Task 7: 自定义怪物DAT与新版登录器只读验收门禁

**Files:**
- Create: `E:\XuanYuanDevPlatform\src\xydp\monster_login_integration.py`
- Create: `E:\XuanYuanDevPlatform\tests\test_monster_login_integration.py`
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_library.py:133-158,1215-1238,1315-1347`

**Interfaces:**
- Produces: `LoginIntegrationStatus`.
- Produces: `read_makegamelogin_config(config_path: Path) -> dict[str, str]`.
- Produces: `verify_custom_monster_login(generator_dir: Path, dat_path: Path, launcher_path: Path, dependency_paths: Sequence[Path]) -> LoginIntegrationStatus`.

- [ ] **Step 1: 写登录器门禁失败测试**

```python
def test_config_requires_enabled_flag_and_exact_dat_path(self): ...
def test_launcher_must_be_newer_than_dat_ini_and_effect_list(self): ...
def test_gb18030_config_is_read_without_reencoding(self): ...
def test_standard_appr_plan_does_not_require_custom_dat(self): ...
def test_smartmonster_receipt_is_awaiting_client_integration(self): ...
```

- [ ] **Step 2: 运行RED**

Run: `py -3 -m unittest tests.test_monster_login_integration -v`  
Expected: FAIL，缺少模块。

- [ ] **Step 3: 实现Config.ini只读解析**

按`utf-8-sig -> gb18030`检测，读取且不回写：

```python
required = {
    "集成怪物配置": "1",
    "怪物配置文件": str(dat_path.resolve()),
}
```

路径比较使用Windows大小写不敏感的绝对路径规则。

- [ ] **Step 4: 实现时间与哈希证据**

检查DAT、目标登录器和依赖文件存在；登录器`st_mtime_ns`必须大于DAT及本批最新INI/EffectImageList。返回`ready`、`missing_dat`、`generator_not_configured`或`launcher_stale`及用户可执行步骤。

- [ ] **Step 5: 接入计划摘要和事务回执**

`plan_summary`和receipt输出两个布尔值、DAT建议路径以及状态`deployed-awaiting-client-integration`；普通Appr事务保持原状态。

- [ ] **Step 6: 运行GREEN**

Run:

```powershell
py -3 -m unittest tests.test_monster_login_integration tests.test_monster_library -v
```

Expected: 全部PASS；测试仅操作临时Config.ini、DAT和假登录器文件。

- [ ] **Step 7: 用当前已验收星辰怪13做只读现场复核**

调用验收函数读取`D:\素材文件夹\LFM2[20260707]\登录器\Config.ini`、`D:\MirServer\Mir200\自定义怪物.dat`和`E:\11周年\传奇登陆器.exe`；Expected: 返回ready且零写入。该结果仅验证当前星辰怪13链，不替代V3新怪游戏验收。

---

### Task 8: GUI与CLI切换到V3引擎规则

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\gui.py:830-920,1429-1653`
- Modify: `E:\XuanYuanDevPlatform\src\xydp\cli.py:174-199,550-579`
- Modify: `E:\XuanYuanDevPlatform\tests\test_monster_gui_default_paths.py`
- Create or Modify: `E:\XuanYuanDevPlatform\tests\test_monster_cli_v3.py`

**Interfaces:**
- Consumes: V3 scan result、plan summary和login integration status。
- Produces CLI option `--donor-server-root` and command `monster-login-verify`.

- [ ] **Step 1: 写界面与CLI失败测试**

```python
def test_gui_uses_engine_rule_scan_language_not_appr_only_language(self): ...
def test_gui_lists_engine_mode_closure_status_and_login_policy(self): ...
def test_cli_accepts_optional_donor_server_root(self): ...
def test_cli_login_verify_is_read_only_json_command(self): ...
```

- [ ] **Step 2: 运行RED**

Run:

```powershell
py -3 -m unittest tests.test_monster_gui_default_paths tests.test_monster_cli_v3 -v
```

Expected: FAIL，旧GUI仍显示“按实测公式Appr//10+1”。

- [ ] **Step 3: 更新扫描区和只读供体根目录回显**

按钮改为“按引擎规则扫描供体并重建V3怪物库”；默认从DB推导根目录，只有高级覆盖时使用CLI参数，不增加表格必填项。

- [ ] **Step 4: 更新列表列与状态筛选**

列固定为：预览、库编号、怪物名称、引擎模式、Appr、闭包状态、依赖数量、登录器要求、说明。缩略图仍可缺失，但不能改变闭包状态显示。

- [ ] **Step 5: 更新预检、确认框和完成提示**

SmartMonster计划必须显示INI数、依赖数、目标EffectImageList条目和“待生成DAT/登录器”；删除“生成器已打开，你只需生成登录器”的无条件成功话术。平台不自动点击或填写MakeGameLogin。

- [ ] **Step 6: 接入CLI JSON合同**

`monster-library-scan`增加可选供体根目录；`monster-login-verify`只读输出Config、DAT、登录器时间和状态，不提供`--apply`。

- [ ] **Step 7: 运行GREEN和GUI导入烟测**

Run:

```powershell
py -3 -m unittest tests.test_monster_gui_default_paths tests.test_monster_cli_v3 -v
py -3 -m py_compile src\xydp\gui.py src\xydp\cli.py
```

Expected: 全部PASS，Tkinter模块可导入，默认路径为E盘平台和客户端。

---

### Task 9: V2备份迁移、文档与接口沉淀

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\monster_catalog_v3.py`
- Modify: `E:\XuanYuanDevPlatform\README.md`
- Modify: `E:\XuanYuanDevPlatform\接口\30_星辰怪首饰店一键生成接口.txt`
- Modify: `E:\XuanYuanDevPlatform\bin\玄渊成果平台使用手册\Codex维护记录\生成工具\build_illustrated_manual.py:427-440,481-499`
- Modify: `E:\XuanYuanDevPlatform\tests\test_monster_catalog_v3.py`
- Modify: `E:\XuanYuanDevPlatform\tests\test_player_facing_language.py`

**Interfaces:**
- Produces: `backup_v2_catalog(catalog_path: Path, backup_root: Path) -> Path`.
- Produces user workflow: 保存并关闭XLSX→V3预检→一键同步→人工生成DAT→登录器集成→游戏动作验收。

- [ ] **Step 1: 写迁移与文案失败测试**

```python
def test_v2_catalog_is_backed_up_before_v3_replace(self): ...
def test_large_assets_are_reused_by_hash_not_duplicated(self): ...
def test_manual_never_claims_thumbnail_equals_complete_patch(self): ...
def test_interface_marks_star13_game_verified_and_v3_as_default_future_route(self): ...
```

- [ ] **Step 2: 运行RED**

Run:

```powershell
py -3 -m unittest tests.test_monster_catalog_v3 tests.test_player_facing_language -v
```

Expected: 新迁移和文案测试FAIL。

- [ ] **Step 3: 实现V2目录一次性备份**

重建V3前将旧`catalog.sqlite`复制到事务目录并回读哈希；资产目录不整库复制，V3本地化时按SHA256复用已有文件。重建失败时旧catalog仍在原位。

- [ ] **Step 4: 更新接口最高优先级结论**

接口文件开头新增：星辰怪13已完成身体及五类动作游戏验收；后续怪物默认走通用V3，专用star13脚本只作黄金证据和回滚，不再作为批量入口。

- [ ] **Step 5: 更新README与图文手册生成源**

写清两种引擎模式、状态含义、用户最简操作、DAT人工步骤和“不新增刷新/爆率”边界；截图路径只作示例，运行前读取当前配置。

- [ ] **Step 6: 运行GREEN与手册源检查**

Run:

```powershell
py -3 -m unittest tests.test_monster_catalog_v3 tests.test_player_facing_language -v
py -3 -m py_compile 'bin\玄渊成果平台使用手册\Codex维护记录\生成工具\build_illustrated_manual.py'
```

Expected: 全部PASS，无旧“所有怪物统一Appr公式即完整补丁”的活动文案。

- [ ] **Step 7: 记录V2/V3迁移检查点**

保存旧catalog哈希、备份哈希、V3 catalog哈希和资产复用计数到`evidence\monster-library-v3\task-09.json`。

---

### Task 10: 全量回归、隔离发布和正式端零漂移验收

**Files:**
- Modify only if verification exposes a scoped defect: files owned by Tasks 1-9.
- Create: `E:\XuanYuanDevPlatform\evidence\monster-library-v3\release-verification.json`
- Update at completion: `D:\codex交班记录\YYYYMMDD_HHMM_怪物库V3平台修复待游戏验收.txt`
- Update at completion: `D:\codex交班记录\00_任务总结索引.txt`
- Update at completion: `D:\codex交班记录\01_最近任务指针.txt`

**Interfaces:**
- Consumes all prior task outputs.
- Produces a built GUI/CLI, isolated transaction evidence, rollback evidence and a candidate status awaiting one new V3 monster game test.

- [ ] **Step 1: 运行怪物专项测试**

Run:

```powershell
Set-Location 'E:\XuanYuanDevPlatform'
$env:PYTHONPATH='E:\XuanYuanDevPlatform\src'
py -3 -m unittest tests.test_monster_engine tests.test_monster_catalog_v3 tests.test_monster_smart_transaction tests.test_monster_login_integration tests.test_monster_library tests.test_monster_workbook tests.test_monster_gui_default_paths tests.test_monster_cli_v3 tests.test_deploy_star_monster13_smartmonster -v
```

Expected: 0 failures、0 errors、0 unexpected skips。

- [ ] **Step 2: 运行平台全量测试**

Run:

```powershell
py -3 -m unittest discover -s tests -v
```

Expected: 0 failures、0 errors；与怪物V3无关的既有失败必须单独记录，禁止通过放宽断言掩盖。

- [ ] **Step 3: 编译所有V3相关模块**

Run:

```powershell
py -3 -m py_compile src\xydp\monster_engine.py src\xydp\monster_catalog_v3.py src\xydp\monster_smart_transaction.py src\xydp\monster_login_integration.py src\xydp\monster_library.py src\xydp\monster_workbook.py src\xydp\gui.py src\xydp\cli.py
```

Expected: exit code 0。

- [ ] **Step 4: 执行双路径隔离事务**

使用临时目标A验证普通Appr；临时目标B验证SmartMonster。两边均执行`preflight -> install -> repeated preflight -> rollback -> preflight`。Expected: 状态分别为ready、deployed、already-deployed、rolled-back、ready，回滚后所有目标哈希恢复。

- [ ] **Step 5: 验证V3表格属性边界**

用包含新怪、已有怪保模、显式SmartMonster和模型留空四行的临时XLSX预检。Expected: 用户属性逐字段一致、供体属性泄漏为0、默认随机不选opaque或复杂模型、MonGen与MonItems零变化。

- [ ] **Step 6: 运行正式端零漂移检查**

将执行前记录的正式端哈希与当前值比较，至少包括：

```text
D:\MirServer\Mud2\DB\ApexM2.DB
D:\MirServer\Mir200\Envir\MonGen.txt
D:\MirServer\Mir200\Envir\EffectImageList.txt
D:\MirServer\Mir200\Envir\SmartMonster\星辰怪13.ini
E:\11周年\data\XY_StarMon13.wzl
E:\11周年\data\XY_StarMon13.wzx
```

Expected: 全部不变。

- [ ] **Step 7: 构建便携GUI和CLI**

Run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File 'E:\XuanYuanDevPlatform\build.ps1'
```

Expected: 平台测试、装备子项目测试、GUI PyInstaller和CLI PyInstaller全部exit code 0；`bin\XuanYuanDevPlatform.exe`与`bin\xydp-cli.exe`最后写入时间更新。

- [ ] **Step 8: 便携版只读烟测**

启动便携GUI只验证窗口、V3怪物库列项和默认路径，不触发扫描或安装；CLI运行`--help`和临时目录`monster-login-verify`。Expected: 无异常、无正式端写入。若Windows Computer Use不可用，记录为UI人工待验收，不使用SendKeys绕过。

- [ ] **Step 9: 写release-verification.json**

记录专项测试、全量测试、编译、隔离事务、正式端哈希、构建产物哈希、未解决项和`candidate-awaiting-new-monster-game-validation`状态。

- [ ] **Step 10: 交班与临时材料清理**

写独立交班记录并更新索引/指针；将新的工具遇阻写入`D:\codex交班记录\codex遇阻情况`。确认所有验证证据和必要回执已留存后，删除本轮临时模拟目录、测试缓存和源码备份；不删除正式事务历史或用户业务资产。

---

## Spec Coverage Matrix

| Spec requirement | Implementing task |
|---|---|
| 普通Appr与SmartMonster分流 | Tasks 1, 3 |
| V3多依赖目录与状态 | Task 2 |
| 供体引擎根目录、INI、EffectImageList扫描 | Task 3 |
| 目标零基重定位、独立资源、INI全重写 | Task 4 |
| 单事务提交、回读、回滚、漂移门禁 | Task 5 |
| 用户属性与供体属性分离、稳定随机 | Task 6 |
| DAT与新登录器只读验收 | Task 7 |
| GUI/CLI用户流程与状态展示 | Task 8 |
| V2迁移、接口、README、手册 | Task 9 |
| 专项/全量测试、隔离事务、构建、零漂移 | Task 10 |
| 不新增刷新、爆率、地图、NPC和AI | Global Constraints, Tasks 5, 10 |
| 复杂能力和难解析资源安全跳过 | Tasks 1, 3, 6 |
| 星辰怪13通用黄金样本 | Tasks 1, 3, 10 |

## Execution Checkpoints

1. Task 1-3完成后暂停审查：只读V3扫描能否正确产生星辰怪13通用闭包。
2. Task 4-5完成后暂停审查：隔离SmartMonster事务与回滚是否逐字节闭环。
3. Task 6-8完成后暂停审查：表格属性、随机池、登录器门禁和界面是否符合用户最简操作。
4. Task 9-10完成后暂停审查：全量测试、构建和正式端零漂移是否通过。
5. 平台候选完成后，由用户另选一只新怪进行真实V3一键植入和游戏五动作验收；该动作不包含在本计划的自动执行授权中。

