# XLSX 驱动的批量做装备 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 XLSX 的名称、部位、来源编号和属性成为唯一业务输入，平台自动从当前目标服选择同部位基础母版并确保脚本属性生成 ItemDescList 提示文字。

**Architecture:** 保留 `xy_batch_equip_maker` 将 XLSX 行转换为 TXT 的职责，但取消解析阶段的旧服模板名称注入。`xy_equip_maker` 在已经绑定目标 SQLite 数据库的预检/临时安装上下文中解析基础母版：显式模板优先，否则按部位 StdMode 和最小 Idx 选择；目标服没有同部位基础记录时，再使用平台 `slot_base_profiles.json` 的无业务基础结构。所选来源保存在 `EquipmentSpec`，以便现有插入、Shape 继承、日志和事务逻辑继续使用。

**Tech Stack:** Python 3.12、SQLite、unittest、现有 GB18030 Mir 文本写入、PyInstaller GUI/CLI。

## Global Constraints

- 不修改 `XuanYuanItems.xlsx`、真实 `D:\MirServer` 或真实客户端 data。
- XLSX 无模板列时不得再写入旧服 `测试戒/雷纹链/青铜靴/青铜带` 名称。
- 自动选择必须只接受与部位 `STD_MODE_BY_SLOT` 一致的目标服 `StdItems` 记录，按 `Idx` 升序稳定选择。
- 没有同部位目标结构时使用平台基础结构；平台也没有该 StdMode 结构时必须阻止，不允许零字段/半成品生成。
- 资源图严格使用来源编号；无 Shape 映射的动作部位继承自动基础母版 Shape。
- 脚本效果仍走统一 QFunction；ItemDescList 仅做提示显示。
- 所有生成/验证使用临时夹具；正式 EXE 仅在全部测试后重建。

---

### Task 1: 移除 XLSX 解析期的旧服模板名注入

**Files:**
- Modify: `D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_batch_equip_maker.py`
- Modify: `D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_equip_maker.py`
- Test: `D:\XuanYuanDevPlatform\做装备\tests\test_equipment_batch_and_native.py`

**Interfaces:**
- Consumes: `row_to_equipment_txt(row) -> str` 和 `parse_spec(path) -> EquipmentSpec`。
- Produces: 没有显式模板列的 XLSX/TXT 将保留 `EquipmentSpec.template == ""`，但仍填写 `fields["StdMode"]`。

- [ ] **Step 1: 写失败测试**

在 `test_equipment_batch_and_native.py` 增加：

```python
def test_xlsx_slot_keeps_template_unresolved_until_target_selection(self):
    spec_path = self.write_spec("[装备]\\n名称=自动戒指\\n部位=戒指\\n")
    spec = xy_equip_maker.parse_spec(spec_path)
    self.assertEqual(spec.template, "")
    self.assertEqual(spec.fields["StdMode"], 22)
```

并将旧的“默认模板为青铜头盔”断言改为“模板为空、StdMode=15”。

- [ ] **Step 2: 运行失败测试**

Run:

```powershell
$env:PYTHONPATH='D:\XuanYuanDevPlatform\src;D:\XuanYuanDevPlatform\做装备\src'
python -m unittest -v 做装备.tests.test_equipment_batch_and_native.EquipmentNativeAndBatchTests.test_xlsx_slot_keeps_template_unresolved_until_target_selection
```

Expected: FAIL，因为当前 `parse_spec` 把 `DEFAULT_TEMPLATE_BY_SLOT` 写入 `spec.template`。

- [ ] **Step 3: 最小实现**

删除 `parse_spec` 中以下解析期赋值，不删除 `STD_MODE_BY_SLOT`：

```python
if spec.slot and not spec.template:
    spec.template = DEFAULT_TEMPLATE_BY_SLOT.get(spec.slot, "")
```

删除 `xy_batch_equip_maker.row_to_equipment_txt` 中“没有默认模板则要求填写模板”的分支。显式 XLSX `模板` 列仍原样写入 TXT。

- [ ] **Step 4: 运行任务测试**

Run:

```powershell
python -m unittest -v 做装备.tests.test_equipment_batch_and_native
```

Expected: PASS，且 `row_to_equipment_txt` 不会要求 XLSX 用户填写模板。

### Task 2: 在目标数据库上下文自动解析基础母版

**Files:**
- Modify: `D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_equip_maker.py`
- Test: `D:\XuanYuanDevPlatform\做装备\tests\test_equipment_preflight.py`
- Test: `D:\XuanYuanDevPlatform\做装备\tests\test_equipment_transaction.py`

**Interfaces:**
- Consumes: `EquipmentSpec(slot, template, fields)`、当前 `DB_PATH` 和 `STD_MODE_BY_SLOT`。
- Produces: `resolve_template_for_spec(spec, conn) -> dict`，并把自动选择的 `Name` 写回 `spec.template`；找不到时抛出 `EquipMakerError`。

- [ ] **Step 1: 写失败测试**

在预检夹具数据库插入两个戒指母版，Idx 分别为 50/10、StdMode 均为 22；编译无 `模板` 的 XLSX 行并预检：

```python
plan = planner.preflight(target, compiled)
self.assertEqual(plan.blockers, [])
```

在安装后读取 `StdItems` 新行，断言继承低 Idx 母版的 `Shape`/`Weight`。另加无 StdMode=22 行时：

```python
self.assertTrue(any("缺少同部位基础结构" in item and "StdMode=22" in item for item in plan.blockers))
```

- [ ] **Step 2: 运行失败测试**

Run:

```powershell
python -m unittest -v 做装备.tests.test_equipment_preflight.EquipmentPreflightTests.test_ring_without_xlsx_template_selects_lowest_idx_slot_base
```

Expected: FAIL，当前逻辑仍查找旧的 `测试戒`。

- [ ] **Step 3: 最小实现**

在 `xy_equip_maker.py` 添加：

```python
def resolve_template_for_spec(spec: EquipmentSpec, conn: sqlite3.Connection) -> dict:
    expected = STD_MODE_BY_SLOT.get(spec.slot)
    if spec.template:
        row = get_item(conn, spec.template)
        if row is None:
            raise EquipMakerError(f"模板装备不存在，已停止：{spec.template}")
        if expected is not None and int(row.get("StdMode", 0)) != expected:
            raise EquipMakerError(f"模板装备部位不匹配：{spec.template} StdMode={row.get('StdMode')}，部位={spec.slot} 需要 StdMode={expected}")
        return row
    if expected is None:
        raise EquipMakerError(f"未知部位缺少基础母版规则：{spec.slot}")
    row = first_stditem_by_stdmode(conn, expected)
    if row is None:
        raise EquipMakerError(f"目标服缺少同部位基础结构：部位={spec.slot}，StdMode={expected}")
    spec.template = str(row["Name"])
    return row
```

让 `validate_template_exists`、`preflight`、`insert_stditem` 都使用该函数；`insert_stditem` 必须复用已解析的同一母版，而不能回退为零字段。查询必须 `ORDER BY Idx ASC LIMIT 1`。

- [ ] **Step 4: 运行任务测试**

Run:

```powershell
python -m unittest -v 做装备.tests.test_equipment_preflight 做装备.tests.test_equipment_transaction
```

Expected: PASS，自动选择正确目标母版；目标缺母版时使用平台基础结构；事务回滚保持逐字节恢复。

### Task 3: 验证 Shape 回退和脚本属性提示文字

**Files:**
- Modify: `D:\XuanYuanDevPlatform\做装备\src\xyequip\legacy\xy_equip_maker.py`（仅在测试表明现有路径遗漏时）
- Test: `D:\XuanYuanDevPlatform\做装备\tests\test_equipment_batch_and_native.py`
- Test: `D:\XuanYuanDevPlatform\做装备\tests\test_equipment_transaction.py`

**Interfaces:**
- Consumes: 自动解析后的 `spec.template`、`spec.script_attrs`、`desc_line(spec, registry)`。
- Produces: 无资源 Shape 映射的动作部位继承母版 `Shape`；脚本属性存在于 `ItemDescList` 对应装备行。

- [ ] **Step 1: 写失败测试**

使用临时武器母版 `StdMode=5, Shape=77` 和无 Shape 映射的来源编号，调用自动母版解析/插入：

```python
self.assertEqual(created_row["Shape"], 77)
```

再用 XLSX 行 `神力倍攻=20, 打怪伤害=30, 暴击伤害=40, 固定切割=500` 安装后断言：

```python
text = item_desc.read_bytes().decode("gb18030")
self.assertIn("神力倍攻+20%", text)
self.assertIn("打怪伤害+30%", text)
self.assertIn("暴击伤害+40%", text)
self.assertIn("固定切割+500", text)
```

- [ ] **Step 2: 运行失败测试**

Run:

```powershell
python -m unittest -v 做装备.tests.test_equipment_transaction.EquipmentTransactionTests.test_auto_template_weapon_keeps_base_shape_and_script_tooltip
```

Expected: FAIL，直到自动母版解析在临时安装路径生效；若脚本提示已有实现，显示断言通过并记录为既有能力。

- [ ] **Step 3: 最小实现**

不新增 M2 自定义属性绑定。确保自动母版在 `insert_stditem` 的 `INHERIT_FIELDS` 路径中提供 Shape；检查 `parse_spec` 对 `[特殊属性]` 同时填充 `script_attrs` 和 `desc_attrs`。仅在遗漏时补充：

```python
spec.script_attrs[key] = value
spec.desc_attrs[key] = value
```

`desc_line` 保持使用 `script_properties.json` 的 label/unit。

- [ ] **Step 4: 运行任务测试**

Run:

```powershell
python -m unittest -v 做装备.tests.test_equipment_batch_and_native 做装备.tests.test_equipment_transaction
```

Expected: PASS，静态图导入规则不变、动作 Shape 回退可读、脚本属性提示文字存在。

### Task 4: 文档、全量验证和正式 EXE

**Files:**
- Modify: `D:\XuanYuanDevPlatform\做装备\docs\批量做装备使用说明.md`
- Modify: `D:\codex交班记录\玄渊成果植入平台_完整使用说明_ChatGPT必读.txt`
- Modify: `D:\XuanYuanDevPlatform\做装备\evidence\automated\README.md`
- Modify: `D:\XuanYuanDevPlatform\做装备\evidence\automated\acceptance.json`
- Create: 在 `D:\codex交班记录` 下用 `Get-Date -Format yyyyMMdd_HHmm` 生成前缀的“实现XLSX自动模板匹配”交班 TXT。

**Interfaces:**
- Consumes: 完成的自动母版/提示文字行为和测试结果。
- Produces: 用户操作说明、候选状态证据和长期交班记录。

- [ ] **Step 1: 备份关键源文件与说明**

Run:

```powershell
$backup="D:\XuanYuanDevPlatform\backups\equipment-migration\xlsx-auto-template_$(Get-Date -Format yyyyMMdd_HHmmss)"
```

复制本计划涉及的既有源码、测试、说明、索引和最近任务指针到该目录。

- [x] **Step 2: 更新用户说明**

说明中明确：用户只填来源编号、部位和属性；平台按目标服自动选内部基础母版；预检报告会显示自动选中的母版；武器/衣服无 Shape 映射时继承基础母版动作；脚本属性通过 ItemDescList 提示文字显示。

- [x] **Step 3: 全量验证与构建**

Run:

```powershell
cd D:\XuanYuanDevPlatform
& .\build.ps1
```

Expected: 平台测试和做装备测试全通过，`bin\XuanYuanDevPlatform.exe`、`bin\xydp-cli.exe` 构建成功。

- [x] **Step 4: 隔离实际预检/安装验证**

创建只含目标特征、SQLite 基础母版和合成三图库的 `testbeds` 夹具；用官方 CLI 执行 `equipment-preflight` 和 `equipment-apply --yes`。核对：不要求旧模板名、自动选中母版、生成 DB 行继承 Shape、ItemDescList 含脚本属性提示、三图库追加成功、回滚恢复服务端文件。

- [x] **Step 5: 记录证据和交班**

更新自动验收计数、写入独立交班 TXT、更新 `00_任务总结索引.txt` 和 `01_最近任务指针.txt`。状态保持 `待验证`，直到独立真实测试服完成 M2 与游戏内显示/属性验收。
