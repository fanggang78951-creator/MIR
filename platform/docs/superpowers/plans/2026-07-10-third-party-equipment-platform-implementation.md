# 玄渊第三方做装备平台实施计划

> **执行要求：** 按任务顺序实施；每一任务先写失败测试，再做最小实现，再运行指定验证。`D:\XuanYuanDevPlatform` 不是 Git 仓库，因此以时间戳备份、哈希清单和验证记录替代每步提交。实施过程中不得初始化 Git、不得修改装备属性语义、不得直接在正式服试错。

**目标：** 把 `D:\MirServer旧\AI_Handoff` 中已经成熟的批量做装备工具、装备源表格式、脚本属性与资源处理能力迁入 `D:\XuanYuanDevPlatform\做装备`，并接入成果植入平台，使其可对任意同引擎服务端执行预检、生成、安装与逐字节回滚。GUI 默认目标为 `D:\MirServer`，但用户可替换为任意目录。

**架构原则：** 原装备生成算法作为受保护的兼容核心迁入平台；新代码只负责路径上下文、目标识别、计划、事务、GUI 和 CLI。批量 XLSX 是唯一公开制作入口，单件 TXT 能力只作为内部兼容层。所有目标文件先在事务临时区生成和校验，成功后再原子替换。旧目录仅在新平台通过全套验证后迁移到平台归档，绝不删除成果。

**技术栈：** Python 3.12、Tkinter/ttk、stdlib `sqlite3`、stdlib ZIP/XML XLSX 读取、PyInstaller、`unittest`/现有 pytest 测试入口、PowerShell。

---

## 固定边界与验收口径

- 保留 `script_properties.json` 的全部属性定义、标签、变量、anchor 和显示规则。
- 保留 `XuanYuanItems.xlsx` 的列名、列序、空白语义、原生 Element 映射、固定三表路线和绿字规则。
- 默认服务端为 `D:\MirServer`，但代码中的所有输入/输出必须由 `EquipmentPaths` 实例解析。
- 平台母版、模板、证据、历史归档都留在 `D:\XuanYuanDevPlatform\做装备`；目标服只写装备所需文件和最小安装收据。
- 目标服运行中的 M2、缺失 ApexM2.DB/Envir、重复装备、资源编号冲突、脚本 anchor 冲突、编码无法往返时阻止正式生成。
- 正式安装必须备份所有受影响文件；任何一步失败不留下半成品；回滚逐字节恢复。
- 迁入后先标记 `candidate`；独立同引擎新服完成 M2 启动和游戏内验收后才允许标记 `verified`。

## 非 Git 项目的检查点规则

每个任务完成后生成：

```text
D:\XuanYuanDevPlatform\backups\equipment-migration\task-NN_YYYYMMDD_HHMMSS\
  changed-files\
  SHA256SUMS.json
  test-output.txt
```

修改既有文件前，将原文件复制到该任务的 `changed-files`，并记录 SHA-256。新增文件只记录新文件哈希。任务验证失败时，从该目录逐字节恢复既有文件并删除本任务未通过的新文件。

---

## 任务 1：建立迁移清单、黄金样本和不可变契约

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\migration\source_inventory.json`
- 新建：`D:\XuanYuanDevPlatform\做装备\evidence\baseline\source_hashes.json`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_legacy_contract.py`
- 复制：`D:\MirServer旧\AI_Handoff\tools\xy_equip_maker\tests\test_equipment_batch_and_native.py`
- 读取：`D:\MirServer旧\AI_Handoff\装备源表\XuanYuanItems.xlsx`
- 读取：`D:\MirServer旧\AI_Handoff\装备源表\批量装备模板.xlsx`

### 步骤 1：先写失败的契约测试

测试必须断言：

```python
def test_required_source_artifacts_are_registered():
    assert inventory["tool"]["script_properties.json"]["sha256"]
    assert inventory["source_tables"]["XuanYuanItems.xlsx"]["sha256"]

def test_xlsx_header_contract_is_frozen():
    assert read_headers(master_xlsx) == expected_headers

def test_property_registry_is_lossless():
    assert migrated_registry == source_registry
```

首次运行：

```powershell
Set-Location D:\XuanYuanDevPlatform
python -m pytest 做装备\tests\test_legacy_contract.py -q
```

预期：因清单和迁移母版尚不存在而失败。

### 步骤 2：生成受控源清单

只登记以下范围，不扫描整个 D 盘：

- `D:\MirServer旧\AI_Handoff\tools\xy_equip_maker`
- `D:\MirServer旧\AI_Handoff\装备源表`
- 旧工具实际 import/调用到的 `xy_data_tool` 脚本及其直接数据文件
- 相关使用说明与已读取的装备交班记录

每条记录包含：`source_path`、`relative_target`、`size`、`mtime`、`sha256`、`role`、`migration_state`、`notes`。`output` 历史只列目录摘要，不逐文件复制进运行核心。

### 步骤 3：冻结黄金输出

使用测试夹具而非真实服务端，为以下输入保存解析结果和生成文本哈希：

- 原生 Element 属性
- 攻击速度正值 `Mac2`
- 固定三表攻击/魔法/道术加成
- 神力、打怪伤害、暴击、爆率、最大爆率、首刀、尾刀、鞭尸
- 图标来源编号和备注

黄金样本写入 `D:\XuanYuanDevPlatform\做装备\evidence\baseline\golden_contract.json`。

### 步骤 4：验证并记录检查点

```powershell
python -m pytest 做装备\tests\test_legacy_contract.py -q
python -m pytest D:\MirServer旧\AI_Handoff\tools\xy_equip_maker\tests\test_equipment_batch_and_native.py -q
```

预期：全部通过；保存测试输出和哈希。

---

## 任务 2：建立独立目录并原样复制兼容核心

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\__init__.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\__init__.py`
- 复制：`D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_equip_maker.py`
- 复制：`D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_batch_equip_maker.py`
- 复制：`D:\XuanYuanDevPlatform\做装备\profiles\script_properties.json`
- 复制：`D:\XuanYuanDevPlatform\做装备\templates\XuanYuanItems.xlsx`
- 复制：`D:\XuanYuanDevPlatform\做装备\templates\批量装备模板.xlsx`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_migrated_core_parity.py`

### 步骤 1：写核心等价性测试

对同一行源数据分别调用旧核心和迁入核心，断言：

```python
assert migrated.row_to_equipment_txt(row) == legacy.row_to_equipment_txt(row)
assert asdict(migrated.parse_spec(txt)) == asdict(legacy.parse_spec(txt))
assert migrated.build_qfunction_text(spec, registry) == legacy.build_qfunction_text(spec, registry)
```

首次运行应因迁入模块不存在而失败。

### 步骤 2：复制而不改写算法

用 `Copy-Item -LiteralPath` 做首次原样复制，复制后立即比较 SHA-256。只允许做两类导入包装修改：

1. `xy_batch_equip_maker` 使用包内相对导入。
2. `SCRIPT_PROPS` 与模板定位改由稍后注入的路径上下文提供。

本任务阶段不得修改字段映射、默认模板、固定表索引、QFunction 内容、颜色码和属性单位。

### 步骤 3：验证

```powershell
$env:PYTHONPATH='D:\XuanYuanDevPlatform\做装备\src'
python -m pytest 做装备\tests\test_migrated_core_parity.py 做装备\tests\test_legacy_contract.py -q
```

预期：所有黄金结果与旧核心一致。

---

## 任务 3：引入可替换路径上下文，消除固定服务端依赖

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\paths.py`
- 修改：`D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_equip_maker.py`
- 修改：`D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_batch_equip_maker.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_equipment_paths.py`

### 步骤 1：写路径隔离失败测试

```python
def test_default_target_is_mirserver():
    assert EquipmentPaths.default(platform_root).server_root == Path(r"D:\MirServer")

def test_all_target_paths_follow_selected_server(tmp_path):
    p = EquipmentPaths.for_target(platform_root, tmp_path / "NewServer")
    assert p.db_path == tmp_path / "NewServer/Mud2/DB/ApexM2.DB"
    assert p.qfunction == tmp_path / "NewServer/Mir200/Envir/Market_Def/QFunction-0.txt"
    assert "MirServer旧" not in str(p)

def test_platform_assets_never_resolve_from_target_ai_handoff(tmp_path):
    assert p.script_properties == platform_root / "做装备/profiles/script_properties.json"
```

### 步骤 2：实现集中路径模型

```python
@dataclass(frozen=True)
class EquipmentPaths:
    platform_root: Path
    server_root: Path = Path(r"D:\MirServer")
    client_data: Path | None = None

    @property
    def db_path(self): return self.server_root / "Mud2/DB/ApexM2.DB"
    @property
    def envir(self): return self.server_root / "Mir200/Envir"
    @property
    def script_properties(self):
        return self.platform_root / "做装备/profiles/script_properties.json"
```

同时覆盖：`ItemDescList.txt`、`ItemRuleList.txt`、`GroupItemList.txt`、`QFunction-0.txt`、资源映射、静态图标工具、raw-clone 工具、备份根、输出根和客户端 data。

### 步骤 3：兼容核心改为显式配置

为核心增加：

```python
def configure_paths(paths: EquipmentPaths) -> None: ...
```

所有旧全局路径只作为当前上下文的派生别名，默认上下文仍指向 `D:\MirServer`。不得从 `server_root\AI_Handoff` 读取平台脚本、属性表或资源程序。

### 步骤 4：验证无硬编码残留

```powershell
rg -n "D:\\MirServer旧|D:\\11周年|D:\\素材文件夹|AI_Handoff\\tools" D:\XuanYuanDevPlatform\做装备\src
python -m pytest 做装备\tests\test_equipment_paths.py 做装备\tests\test_migrated_core_parity.py -q
```

预期：`rg` 无结果；测试通过。允许 `D:\MirServer` 只出现在默认值和对应测试中。

---

## 任务 4：固化批量 XLSX 唯一公开接口

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\source.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\batch.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_xlsx_contract.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\fixtures\workbooks\README.txt`

### 步骤 1：写 XLSX 兼容测试

覆盖：共享字符串、inlineStr、数字、空单元格、空白行、中文列名、别名、绿字 1–20、未知属性报错、重复装备名、保持原始行号。

```python
def test_master_workbook_compiles_without_schema_translation():
    result = compile_workbook(platform_master)
    assert result.headers == frozen_headers
    assert result.rows[0].source_row == 2

def test_unknown_green_property_blocks_plan(): ...
def test_empty_cells_keep_original_semantics(): ...
```

### 步骤 2：实现公开批量接口

```python
class BatchEquipmentService:
    def inspect(self, workbook: Path) -> WorkbookInspection: ...
    def compile(self, workbook: Path, paths: EquipmentPaths) -> BatchCompileResult: ...
```

服务只接受 `.xlsx`/兼容 `.csv`，GUI 只显示 XLSX。内部仍调用迁入核心的 `row_to_equipment_txt`、`parse_spec` 和属性注册表，避免重写规则。

### 步骤 3：输出留在平台

生成的中间 TXT、报告和错误栈保存到：

```text
D:\XuanYuanDevPlatform\做装备\outputs\batch_YYYYMMDD_HHMMSS\
```

不得写回 `D:\MirServer旧\AI_Handoff`，也不得把正式母版放入目标服。

### 步骤 4：验证

```powershell
python -m pytest 做装备\tests\test_xlsx_contract.py 做装备\tests\test_migrated_core_parity.py -q
```

---

## 任务 5：实现第三方目标识别与只读预检计划

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\target.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\planner.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_equipment_preflight.py`

### 步骤 1：写预检失败测试

夹具场景：空白目标、非翎风目录、缺 ApexM2.DB、缺 Envir、M2 正在运行、同名装备、ItemDesc 重复、固定三表重复、QFunction anchor 不唯一、脚本变量/标签冲突、资源来源缺失、客户端路径缺失。

关键断言：

```python
before = tree_hash(target)
plan = planner.preflight(target, workbook)
assert tree_hash(target) == before
assert plan.blockers == []
assert all(change.before_hash is not None or change.kind == "create" for change in plan.changes)
```

### 步骤 2：实现目标识别

要求存在：

- `Mir200\Envir`
- `Mud2\DB\ApexM2.DB`
- 可识别的 `M2Server.exe` 位置或平台目标识别兼容结果

客户端路径只在所选行包含资源复制时必需。纯 DB/脚本装备不得强制客户端。

### 步骤 3：生成结构化计划

```python
@dataclass(frozen=True)
class EquipmentChange:
    path: Path
    kind: Literal["create", "replace"]
    before_hash: str | None
    after_bytes: bytes

@dataclass
class EquipmentPlan:
    target: EquipmentTarget
    workbook_hash: str
    equipment_names: list[str]
    changes: list[EquipmentChange]
    blockers: list[str]
    warnings: list[str]
```

计划预览列出 DB、三表、QFunction、WZL/WZX 和客户端资源变更；不得直接调用旧核心的写入函数处理正式目标。

### 步骤 4：验证

```powershell
python -m pytest 做装备\tests\test_equipment_preflight.py -q
```

---

## 任务 6：把旧生成器包进临时副本事务

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\transaction.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\installer.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_equipment_transaction.py`

### 步骤 1：写事务与回滚失败测试

覆盖：

- 第 N 件生成失败，目标零变化。
- 临时 DB `PRAGMA integrity_check` 失败，目标零变化。
- 原子替换中断，自动恢复。
- 安装成功后逐字节回滚。
- 收据后目标内容被手工修改，阻止覆盖/升级/回滚并报告。
- 相同工作簿重复执行幂等，不重复插三表/QFunction。

```python
assert snapshot_after_failed_apply == snapshot_before
installer.rollback(receipt.transaction_id)
assert snapshot_after_rollback == snapshot_before
```

### 步骤 2：实现临时工作树

正式生成前将受影响文件复制到：

```text
D:\XuanYuanDevPlatform\做装备\backups\<target-id>\<transaction-id>\working\
```

将 `EquipmentPaths.server_root` 指向临时镜像，再调用兼容核心生成。这样保留原工具行为，但任何失败都只污染临时副本。

### 步骤 3：验证临时产物

- SQLite `PRAGMA integrity_check == ok`
- 每个装备名唯一存在
- ItemDesc/ItemRule/GroupItem 唯一
- QFunction 标签唯一、受管块完整、GB18030 可往返
- WZL/WZX 数量及偏移验证
- 计划中的 after hash 与临时产物一致

### 步骤 4：备份并原子提交

备份目标原字节到同一事务目录；逐文件用同目录临时文件 + `os.replace` 提交。若提交阶段失败，使用内存/磁盘备份恢复已经替换的文件。

收据：

```text
D:\XuanYuanDevPlatform\做装备\backups\<target-id>\<transaction-id>\receipt.json
<server>\.xydp\equipment-installed.json
```

目标服收据只保存事务 ID、工作簿哈希、装备名和安装后哈希，不保存源码或平台绝对路径。

### 步骤 5：验证

```powershell
python -m pytest 做装备\tests\test_equipment_transaction.py -q
```

---

## 任务 7：迁入资源桥接能力并解除外部素材目录依赖

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\src\xyequip\resources\__init__.py`
- 复制/修改：`D:\XuanYuanDevPlatform\做装备\src\xyequip\resources\static_icon_from_wzl.py`
- 复制/修改：`D:\XuanYuanDevPlatform\做装备\src\xyequip\resources\clone_wzl_frame_raw.py`
- 复制：`D:\XuanYuanDevPlatform\做装备\profiles\装备资源映射表.csv`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_equipment_resources.py`

### 步骤 1：确认直接依赖

通过 import/调用图只迁入旧核心实际使用的脚本和直接配置，不整包搬入 `xy_data_tool`，不携带无关数据库工具。

### 步骤 2：写资源测试

使用最小 WZL/WZX 二进制夹具验证：raw-clone 逐帧、WZX 偏移、资源编号范围、目标客户端可选路径、服务器/客户端双端计划。

### 步骤 3：路径参数化

资源来源由工作簿行、平台 profile 或 GUI 选择提供；禁止默认读取 `D:\11周年`、`D:\素材文件夹`、旧服 `AI_Handoff`。缺失来源时预检阻止，不做猜测。

### 步骤 4：验证

```powershell
rg -n "D:\\11周年|D:\\素材文件夹|MirServer旧" D:\XuanYuanDevPlatform\做装备\src
python -m pytest 做装备\tests\test_equipment_resources.py -q
```

---

## 任务 8：接入现有 GUI 和 CLI

**文件：**

- 新建：`D:\XuanYuanDevPlatform\src\xydp\equipment_bridge.py`
- 修改：`D:\XuanYuanDevPlatform\src\xydp\gui.py`
- 修改：`D:\XuanYuanDevPlatform\src\xydp\cli.py`
- 新建：`D:\XuanYuanDevPlatform\tests\test_equipment_bridge.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\tests\test_equipment_gui_state.py`

### 步骤 1：备份现有 GUI/CLI 并写失败测试

测试断言：

```python
assert "批量做装备" in TAB_TITLES
assert EquipmentUiState().server_root == r"D:\MirServer"
assert cli_parser.parse_args(["equipment-preflight", "--input", "a.xlsx"]).server == Path(r"D:\MirServer")
```

### 步骤 2：新增“批量做装备”页面

页面仅提供：

- 装备源表（默认平台 `做装备\templates\XuanYuanItems.xlsx`）
- 服务端目录（默认 `D:\MirServer`，可浏览替换）
- 客户端 data（仅资源装备需要）
- “预检”按钮
- 逐装备/逐文件变化列表和阻止项
- “确认生成”按钮
- 安装历史与“逐字节回滚”按钮

不得暴露单件 TXT 编辑、任意脚本执行或直接覆盖开关。

### 步骤 3：增加 CLI

```text
xydp-cli equipment-inspect --input <xlsx>
xydp-cli equipment-preflight --input <xlsx> [--server D:\MirServer] [--client-data <path>]
xydp-cli equipment-apply --input <xlsx> [--server D:\MirServer] --yes
xydp-cli equipment-rollback --server <path> --transaction <id> --yes
```

CLI 和 GUI 必须调用同一个 `BatchEquipmentService/EquipmentInstaller`，不复制业务逻辑。

### 步骤 4：验证

```powershell
$env:PYTHONPATH='D:\XuanYuanDevPlatform\src;D:\XuanYuanDevPlatform\做装备\src'
python -m pytest tests\test_equipment_bridge.py 做装备\tests\test_equipment_gui_state.py -q
python run_cli.py equipment-preflight --input 做装备\templates\XuanYuanItems.xlsx --server D:\XuanYuanDevPlatform\testbeds\equipment-empty
```

---

## 任务 9：更新构建，交付便携 EXE

**文件：**

- 修改：`D:\XuanYuanDevPlatform\build.ps1`
- 修改：`D:\XuanYuanDevPlatform\run_gui.py`
- 修改：`D:\XuanYuanDevPlatform\run_cli.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\build_manifest.json`
- 修改：`D:\XuanYuanDevPlatform\README.md`
- 新建：`D:\XuanYuanDevPlatform\做装备\docs\批量做装备使用说明.md`

### 步骤 1：写冻结构建测试

验证 `sys._MEIPASS`/冻结路径下仍从 EXE 同级平台根读取 `做装备\profiles` 和 `templates`，并可导入 `xyequip`。

### 步骤 2：修改 PyInstaller 路径和数据声明

两条构建命令增加：

```powershell
--paths 做装备\src
--add-data "做装备\profiles;做装备\profiles"
```

模板保持 EXE 外置，便于用户替换/复制，不嵌入只读临时目录。构建后平台目录仍是唯一母版。

### 步骤 3：构建与烟雾测试

```powershell
Set-Location D:\XuanYuanDevPlatform
.\build.ps1
.\bin\xydp-cli.exe equipment-inspect --input .\做装备\templates\XuanYuanItems.xlsx
```

GUI 手工烟雾：打开“批量做装备”，确认默认服务端显示 `D:\MirServer`，改选测试服后预检目标随之改变。

---

## 任务 10：在合成测试服做端到端安装、幂等与回滚

**文件：**

- 新建：`D:\XuanYuanDevPlatform\testbeds\equipment-fixture-builder.py`
- 新建：`D:\XuanYuanDevPlatform\做装备\evidence\automated\README.md`
- 新建：`D:\XuanYuanDevPlatform\做装备\evidence\automated\acceptance.json`

### 步骤 1：创建最小同引擎结构夹具

夹具只包含测试用数据库、Envir/三表/QFunction 和假的 M2 特征文件，不复制用户正式服数据。

### 步骤 2：执行完整流程

1. XLSX 读取和预检，断言目标零写入。
2. 正式生成，断言 DB/三表/QFunction 与预期一致。
3. 再次预检，断言幂等或明确阻止重复装备。
4. 人工修改受管内容，断言升级/回滚阻止并报告。
5. 恢复后回滚，断言目标树逐字节等于安装前。
6. 模拟第 N 件失败，断言目标树零变化。

### 步骤 3：运行全量自动测试

```powershell
Set-Location D:\XuanYuanDevPlatform
$env:PYTHONPATH='D:\XuanYuanDevPlatform\src;D:\XuanYuanDevPlatform\做装备\src'
python -m pytest tests 做装备\tests -q
```

不得因新增装备模块破坏现有成果植入平台测试。

---

## 任务 11：审核迁移、归档旧文件并更新登记表

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\legacy_archive\README.md`
- 更新：`D:\XuanYuanDevPlatform\做装备\migration\source_inventory.json`
- 更新：`D:\XuanYuanDevPlatform\migration\AI_Handoff迁移登记表.csv`（若现有字段兼容）
- 移动：旧工具运行核心、说明、模板到 `D:\XuanYuanDevPlatform\做装备\legacy_archive\source_snapshot_YYYYMMDD`

### 步骤 1：移动前门禁

必须同时满足：

- 全量测试通过。
- EXE/CLI 烟雾通过。
- 平台母版哈希与登记表一致。
- 从新目录执行时不读取旧 `AI_Handoff`。
- 旧输出历史已分类：必要证据归档，其余保留原地，不误搬海量临时输出。

### 步骤 2：先复制快照再移动源文件

先复制旧工具必要文件到 `legacy_archive` 并核验 SHA-256；再把用户明确要求迁移的旧运行文件从 `D:\MirServer旧\AI_Handoff` 移入归档。任何哈希不一致立即停止，不删除、不覆盖。

旧位置留下简短 `已迁移到玄渊平台.txt` 指针，内容只说明正式母版路径和迁移时间。若旧目录内有其他项目引用该工具，先记录为阻止项，不强行移动。

### 步骤 3：状态更新

迁移登记记录 `source_path`、原哈希、目标路径、目标哈希、目标模块、状态、自动测试证据、M2/游戏验证状态。自动测试后状态为 `candidate/待游戏验证`。

---

## 任务 12：真实独立新服验收与最终交班

**文件：**

- 新建：`D:\XuanYuanDevPlatform\做装备\evidence\game\验收记录模板.md`
- 更新：`D:\XuanYuanDevPlatform\做装备\README.md`
- 新建：`D:\codex交班记录\YYYYMMDD_HHMM_第三方做装备平台实施.txt`
- 更新：`D:\codex交班记录\00_任务总结索引.txt`
- 更新：`D:\codex交班记录\01_最近任务指针.txt`

### 步骤 1：独立新服验收

用户提供/选择独立同引擎新服后，在 GUI 中明确确认，至少验证：

- M2 无报错启动。
- 无装备、单件、多件、穿脱、重登刷新。
- 原生属性、三表固定绿字、全部脚本属性互不覆盖。
- 首刀、尾刀、鞭尸、爆率/最大爆率和伤害类属性。
- 带资源装备服务端与客户端显示正确。
- 回滚后 M2 再次无报错启动，文件哈希回到安装前。

### 步骤 2：晋级规则

只有静态检查、自动测试、M2 启动、游戏内测试和回滚五类证据齐全时，将做装备模块从 `candidate` 晋级 `verified`。未提供独立新服时保持 `candidate`，不虚报完成。

### 步骤 3：写交班记录

交班记录必须包含：任务目标、读取文件、修改文件、备份路径、实际执行内容、验证情况、经验沉淀、踩坑风险、下轮建议；状态仅使用“已完成、部分完成、失败、中断、待验证”。同步更新索引和最近任务指针。

---

## 最终验收命令

```powershell
Set-Location D:\XuanYuanDevPlatform
$env:PYTHONPATH='D:\XuanYuanDevPlatform\src;D:\XuanYuanDevPlatform\做装备\src'
python -m pytest tests 做装备\tests -q
rg -n "D:\\MirServer旧|D:\\11周年|D:\\素材文件夹" 做装备\src src
.\build.ps1
.\bin\xydp-cli.exe equipment-inspect --input .\做装备\templates\XuanYuanItems.xlsx
```

验收结果必须满足：全量测试通过；硬编码扫描无旧服/旧客户端/素材盘依赖；两个 EXE 构建成功；GUI 默认目标是 `D:\MirServer` 且可替换；预检零写入；安装失败零残留；回滚逐字节一致；旧工具属性黄金样本完全相同。
