# 十大陆第一批非战斗结构收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成可供用户审核和后续手动导入的转生、回收、NPC、称号卷来源及编码结构第一批定稿。

**Architecture:** 以现有产消V1.1和NPC V1.0为只读基线，输出新版本而不覆盖旧版；所有关系使用稳定资源ID连接，所有尚不能计算的真值写成统一状态“待战斗与经济模型反算”，不伪造临时金额。六份档案只吸收本轮新规则，并明确后续战斗数值入口。

**Tech Stack:** JavaScript、`@oai/artifact-tool`、Markdown、JSON、GitHub Contents/Git Data API。

**Spec:** `docs/superpowers/specs/2026-09-03-first-noncombat-closure.md`

## Global Constraints

- 不修改现有怪物、装备成品表。
- 小卢恩／大卢恩按全名和唯一编码与“XXX的大卢恩”神器隔离。
- 仅取消C1、C2额外大陆收藏材料；保留C3—C10八件及已测试编号。
- 不填写任何战斗真值、最终金额、真实掉率或攻速突破数值。
- 所有合成穿戴物不可回收；图鉴登记不消耗货币。
- `GAMEGOLD` 是元宝，不是金刚石。
- 新版文件不得覆盖旧版；所有结果写入 `outputs/f124f410aa49/20260903_第一批非战斗结构收口/`。
- GitHub目标为 `fanggang78951-creator/MIR` 分支 `codex/elden-c1-c2-20260821`，禁止强推和回退。

---

### Task 1: 建立基线与变更映射

**Files:**
- Read: `outputs/f124f410aa49/20260903_产消闭环与处决韧性框架/十大陆产出消耗闭环总账_V1.1_爆率机制补齐.xlsx`
- Read: `outputs/f124f410aa49/20260902_NPC与配方正式结构/十大陆NPC与配方总账_V1.0.xlsx`
- Read: `outputs/f124f410aa49/20260902_专属与材料编码阶段分配/材料编码数据库.xlsx`
- Create: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/基线与变更映射.json`

**Interfaces:**
- Consumes: 本计划Spec及三份现有权威表。
- Produces: 工作表、列名、目标行、旧值、新值、删除／新增关系和不可自动取码项的机器可读映射。

- [ ] **Step 1: 读取三个工作簿的工作表、关键范围、公式和样式。**
- [ ] **Step 2: 渲染每个将修改工作表的当前关键范围并保存基线预览。**
- [ ] **Step 3: 写入变更映射，明确C1/C2删除项、四段转生、C10材料修正、合成物不可回收、称号卷新表和编码回读项。**
- [ ] **Step 4: 校验映射中没有战斗数值、最终金额或真实掉率。**

### Task 2: 生成产消V1.2与NPC V1.1

**Files:**
- Create: `tmp_first_noncombat/build_first_noncombat.mjs`
- Create: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/十大陆产出消耗闭环总账_V1.2_非战斗结构定稿.xlsx`
- Create: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/十大陆NPC与配方总账_V1.1_非战斗结构定稿.xlsx`
- Create: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/构建校验.json`

**Interfaces:**
- Consumes: Task 1变更映射。
- Produces: 两份不覆盖旧版的新工作簿；后续档案和验证均以其为权威。

- [ ] **Step 1: 编写构建器导入现有工作簿并复制为新版本。**
- [ ] **Step 2: 删除C1/C2收藏材料占位及关系，保留装备图鉴和C3—C10收藏材料。**
- [ ] **Step 3: 把小／大卢恩改为实物转生材料并新增四阶段产出、转生消耗与阶段后回收关系；11—15和16—20专材使用正式名称但编码状态为“待实库回读／待取码”。**
- [ ] **Step 4: 消除C06“小卢恩／大卢恩”歧义，移除转生配方中的通用合成材料，只保留对应阶段专材与金币／元宝方向。**
- [ ] **Step 5: 把C10艾尔登之王材料统一为失温熔炉楔，并将全部合成穿戴物标记为不可回收。**
- [ ] **Step 6: 新增BOSS称号卷来源表和编码／实库回读表，名称与BOSS一一对应，属性及真实掉率字段统一为“待统一战斗／经济反算”。**
- [ ] **Step 7: 导出两份工作簿和构建校验JSON。**

### Task 3: 更新六份项目档案与确认归档

**Files:**
- Create directory: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/项目档案/`
- Create: 该目录下 `00_项目总纲.md`、`01_当前任务指针.txt`、`02_已确认规则与数值.xlsx`、`03_变更记录.md`、`04_每日设计更新.md`、`05_当前有效游戏设计总档.md`
- Create: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/20260903_第一批非战斗结构收口_确认归档.md`

**Interfaces:**
- Consumes: Task 2两份新工作簿及本计划Spec。
- Produces: 与表格同口径的六份连续档案和本批说明。

- [ ] **Step 1: 复制现行六份档案到新目录，不覆盖旧档。**
- [ ] **Step 2: 追加本轮有效规则、职责边界、两项技术遗留解释和下一阶段入口；删除或明确作废冲突旧口径。**
- [ ] **Step 3: 在02工作簿中追加同口径规则、参数状态和索引，保留原格式。**
- [ ] **Step 4: 写确认归档，列出本批完成项、未填真值、人工导入边界和文件清单。**

### Task 4: 完成公式、视觉、关系和哈希验证

**Files:**
- Create: `tmp_first_noncombat/verify_first_noncombat.mjs`
- Create: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/最终验证.json`
- Create: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/公式错误扫描.ndjson`
- Create directory: `outputs/f124f410aa49/20260903_第一批非战斗结构收口/预览/`

**Interfaces:**
- Consumes: Tasks 2—3全部交付文件。
- Produces: 可审计的通过／失败结论和每张改动工作表的视觉预览。

- [ ] **Step 1: 检查两份主表和档案工作簿的工作表、行数、唯一ID、引用关系及公式错误。**
- [ ] **Step 2: 断言C1/C2收藏占位为0、C3—C10八件仍为8、转生20级结构完整、C10材料一致、合成穿戴物可回收项为0。**
- [ ] **Step 3: 断言称号卷与守关BOSS一一对应，所有战斗属性和真实掉率均未被伪填。**
- [ ] **Step 4: 渲染所有改动工作表并逐张检查裁切、换行、列宽和中文显示。**
- [ ] **Step 5: 对此前怪物、装备成品重新计算SHA-256，确认本轮未修改。**

### Task 5: 同步GitHub并回读核验

**Files:**
- Upload: 本批两份主表、六份档案、确认归档、验证JSON、公式扫描、Spec和Plan。

**Interfaces:**
- Consumes: Task 4验证通过的最终文件。
- Produces: 目标分支上的新提交SHA和逐文件回读校验结果。

- [ ] **Step 1: 读取远端分支最新HEAD，确认未回退。**
- [ ] **Step 2: 通过Git Data API创建二进制blob、tree和单次提交，避免逐文件多提交。**
- [ ] **Step 3: 以非强制方式前移目标分支。**
- [ ] **Step 4: 回读提交树并对照本地SHA-256，确认上传范围与内容完全一致。**

