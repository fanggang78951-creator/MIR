# 《艾尔登法环》传奇十大陆联合重做 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据已确认的十大陆规格，生成可校验的怪物、装备、爆率、称号、NPC任务、合成与地图审计母表，并同步更新《艾尔登法环》项目六份核心档案。

**Architecture:** 将全部正式设计先写入规范化JSON，计算与唯一性检查在JSON层完成，XLSX只是公式化展示与施工输入。保留任务、地图和装备故事关系作为稳定身份；旧数值全部隔离到历史记录。生成器只从规范化JSON读数据，验证器同时检查模型公式、跨表引用、地图/来源编号冲突和当前有效档中的废止词句。

**Tech Stack:** Node.js ESM、Node内置`node:test`、`@oai/artifact-tool`、JSON、Markdown、XLSX。

**Spec:** `docs/superpowers/specs/2026-08-20-elden-ring-ten-continent-rebalance-design.md`

## Global Constraints

- 主线固定为10大陆，顺序严格为：漂流群岛、宁姆格福、宁姆格福西域、利耶尼亚海域、湖之利耶尼亚、盖利德、化圣雪原、巨人山顶、亚坛高原、王城罗德尔。
- 第11—13大陆只允许出现在变更记录的历史列，禁止出现在当前有效设计或生成表。
- C1起重做怪物与装备数值；旧数值不得被生成器读取为默认值。
- 保留8个已完成任务及第一大陆3段完整剧情；删除任务直接发称号、永久韧性或永久处决的旧耦合。
- C1—C2强合成数量为0；C3—C10每大陆1—2件，合计11件、部位不重复、成功率100%。
- 每条强合成配方至少含1件本大陆BOSS专属、1件本大陆其他BOSS专属或核心、2件本大陆同部位非BOSS装备、通用材料、稀有材料和货币；跨大陆输入为0。
- 人物爆率只按当前大陆闭环计算，不建立回低大陆参数。
- 地图尺寸完全不参与本轮设计或部署门禁。NPC、刷新点或传送坐标缺失时只把相应施工点标为`待选坐标/阻断部署`；不得猜填坐标或写成已部署。
- 171个地图号、171个供体ID、装备ID、怪物ID、装备来源编号分别唯一；地图号数字后缀与装备来源编号归一化后也必须无冲突。
- 现有冲突已在来源账本锁定替代号，地图号不改：战靴`821→6407`、项链`823→6401`、戒指`824→6403`；实际导入前回写旧制式装备表。
- 规划、可安装、待配置和已部署是不同状态；没有事务收据和进服验收证据不得写`已部署`。
- 表格创建、修改、渲染和公式检查必须使用`@oai/artifact-tool`；生成后扫描`#REF!/#DIV/0!/#VALUE!/#NAME\?/#N/A`。
- 不归档玄渊通用平台、UI或地图工具资料，只引用本项目所需接口和施工状态。
- 推送、创建PR或合并必须另有用户明确授权；未获授权时只保留已验证工作树和本地提交候选。

---

## File Map

### New source-of-truth files

- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/00_Codex执行总说明.md`：执行顺序、状态定义和输入来源。
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/continents.json`：十大陆顺序、地图数量、玩家快照、怪物HP、爆率与韧性母线。
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/maps.json`：171图、供体ID、连接与坐标施工状态；尺寸字段如被保留仅作历史元数据。
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/monsters.json`：553个怪物身份、类型、地图关系、数值与主要专属关系。
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/preserved_tasks.json`：8个保护任务及奖励替代关系。
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/titles_npcs.json`：50档大陆称号、新NPC、对白、材料、货币和奖励。
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/synthesis.json`：11件强合成装备、配方、来源与固定词条。
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/equipment_source_ledger.json`：装备来源编号占用和跨命名空间冲突修复。

### New generated artifacts

- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/01_十大陆联合成长与爆率总表.xlsx`
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/02_十大陆怪物重做母表.xlsx`
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/03_十大陆装备与合成总表.xlsx`
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/04_NPC任务称号与对话总表.xlsx`
- `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/05_地图传送与编号审计.xlsx`

### New tooling and tests

- `tools/game-design/schema.mjs`
- `tools/game-design/model.mjs`
- `tools/game-design/build-workbooks.mjs`
- `tools/game-design/update-core-archive.mjs`
- `tools/game-design/validate-design.mjs`
- `tools/game-design/test/model.test.mjs`
- `tools/game-design/test/ids.test.mjs`
- `tools/game-design/test/monsters.test.mjs`
- `tools/game-design/test/archive.test.mjs`

### Existing files to modify

- `传奇私服之旅/艾尔登法环项目档案/00_项目总纲.md`
- `传奇私服之旅/艾尔登法环项目档案/01_当前任务指针.txt`
- `传奇私服之旅/艾尔登法环项目档案/02_已确认规则与数值.xlsx`
- `传奇私服之旅/艾尔登法环项目档案/03_变更记录.md`
- `传奇私服之旅/艾尔登法环项目档案/04_每日设计更新.md`
- `传奇私服之旅/艾尔登法环项目档案/05_当前有效游戏设计总档.md`

---

### Task 1: Freeze the authoritative input and create normalized schemas

**Files:**
- Create: `tools/game-design/schema.mjs`
- Create: `tools/game-design/test/model.test.mjs`
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/00_Codex执行总说明.md`

**Interfaces:**
- Consumes: the spec and the latest 2026-08-16 six-file archive.
- Produces: `validateContinent(row)`, `validateMap(row)`, `validateDrop(row)`, `validateRecipe(row)`, `assertUnique(rows,key,label)`.

- [ ] **Step 1: Write the schema tests**

```js
import test from "node:test";
import assert from "node:assert/strict";
import { validateContinent, validateRecipe } from "../schema.mjs";

test("continent requires the local-only drop model", () => {
  assert.throws(() => validateContinent({ id: 1, name: "漂流群岛", returnPenalty: 0.5 }), /returnPenalty/);
});

test("strong recipe rejects cross-continent input", () => {
  assert.throws(() => validateRecipe({
    continentId: 3,
    inputs: [{ continentId: 2, role: "material", quantity: 1 }],
  }), /跨大陆输入/);
});
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `node --test tools/game-design/test/model.test.mjs`  
Expected: FAIL because `schema.mjs` does not exist.

- [ ] **Step 3: Implement the schema**

```js
export function validateContinent(row) {
  if (!Number.isInteger(row.id) || row.id < 1 || row.id > 10) throw new Error("大陆ID必须为1—10");
  if ("returnPenalty" in row) throw new Error("returnPenalty不属于当前大陆闭环模型");
  return row;
}

export function validateRecipe(row) {
  if (row.inputs.some(x => x.continentId !== row.continentId)) throw new Error("强合成禁止跨大陆输入");
  const boss = row.inputs.filter(x => x.isBossExclusive).length;
  const otherGear = row.inputs.filter(x => x.role === "same_slot_non_boss_equipment").reduce((n,x) => n + x.quantity, 0);
  const material = row.inputs.some(x => x.role === "common_material" || x.role === "rare_material");
  const currency = row.inputs.some(x => x.role === "currency");
  if (boss < 1 || otherGear < 2 || !material || !currency) throw new Error("强合成输入结构不完整");
  return row;
}

export function assertUnique(rows, key, label) {
  const seen = new Map();
  for (const row of rows) {
    const value = row[key];
    if (seen.has(value)) throw new Error(`${label}重复: ${value}`);
    seen.set(value, row);
  }
}
```

- [ ] **Step 4: Re-run the tests**

Run: `node --test tools/game-design/test/model.test.mjs`  
Expected: PASS.

- [ ] **Step 5: Write the execution README**

The README must state exact source priority: current user decisions → this spec → 2026-08-16 archive → older specialist files; it must also define `规划/可安装/阻断部署/已部署` and list the five generated workbooks.

- [ ] **Step 6: Commit the task when commit authorization exists**

```bash
git add -- tools/game-design/schema.mjs tools/game-design/test/model.test.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/00_Codex执行总说明.md"
git commit -m "feat: define ten-continent design schemas"
```

### Task 2: Encode the ten-continent progression and drop model

**Files:**
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/continents.json`
- Create: `tools/game-design/model.mjs`
- Modify: `tools/game-design/test/model.test.mjs`

**Interfaces:**
- Consumes: `validateContinent()`.
- Produces: `effectiveDropMultiplier(continent)`, `baseDropDenominator(multiplier,itemClass)`, `monsterHp(continentId,type)`, `targetRawMonsterHit(snapshot,lossRate,absorb,skillCoef)`.

- [ ] **Step 1: Add exact model tests**

```js
import { effectiveDropMultiplier, baseDropDenominator, monsterHp } from "../model.mjs";

test("C10 reaches exactly 100x", () => {
  assert.equal(effectiveDropMultiplier({ normalDropPct: 900, maxDropPct: 900 }), 100);
});

test("C8 local common material denominator is 825", () => {
  assert.equal(baseDropDenominator(55, "common_material"), 825);
});

test("C10 gate boss stays below 888 jing", () => {
  assert.equal(monsterHp(10, "gate_boss"), 5_120_000_000_000_000_000n);
  assert.ok(monsterHp(10, "gate_boss") < 8_880_000_000_000_000_000n);
});
```

- [ ] **Step 2: Verify the new tests fail**

Run: `node --test tools/game-design/test/model.test.mjs`  
Expected: FAIL with missing model exports.

- [ ] **Step 3: Create `continents.json` with the exact ten rows from the spec**

Each row must include:

```json
{
  "id": 10,
  "name": "王城罗德尔",
  "mapGroups": 5,
  "mapCount": 19,
  "playerRawAttackCap": 471859200,
  "playerHpReference": 2361960000,
  "normalDropPct": 900,
  "maxDropPct": 900,
  "effectiveDropMultiplier": 100,
  "gateBossHp": "5120000000000000000",
  "resilienceThreshold": 417,
  "cumulativeTitleResilience": 300,
  "currentArmorResilience": 100,
  "fashionResilience": 18,
  "strongSynthesisCount": 2
}
```

- [ ] **Step 4: Implement exact formulas**

```js
const DENOMINATOR_FACTOR = {
  common_material: 15,
  rare_material: 15,
  normal_exclusive: 360,
  map_boss_exclusive: 24,
  gate_boss_exclusive: 10,
};

export const effectiveDropMultiplier = ({normalDropPct,maxDropPct}) =>
  (1 + normalDropPct / 100) * (1 + maxDropPct / 100);

export const baseDropDenominator = (m,itemClass) =>
  Math.ceil(m * DENOMINATOR_FACTOR[itemClass]);

export function monsterHp(continentId,type) {
  const gate = 10_000_000n * 20n ** BigInt(continentId - 1);
  return ({normal: gate * 8n / 1000n, rare: gate * 3n / 100n, map_boss: gate / 5n, gate_boss: gate})[type];
}

export const targetRawMonsterHit = (hp,lossRate,absorb,skillCoef=1) =>
  Math.ceil(lossRate * hp / (1 - absorb) / skillCoef);
```

- [ ] **Step 5: Run tests**

Run: `node --test tools/game-design/test/model.test.mjs`  
Expected: PASS.

- [ ] **Step 6: Commit when authorized**

```bash
git add -- tools/game-design/model.mjs tools/game-design/test/model.test.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/continents.json"
git commit -m "feat: add ten-continent combat and drop curves"
```

### Task 3: Build the 171-map ledger and hard blockers

**Files:**
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/maps.json`
- Create: `tools/game-design/test/ids.test.mjs`

**Interfaces:**
- Consumes: authoritative map workbook and the C3—C10 map overview image data transcribed in the spec audit.
- Produces: 171 map rows, 125 adjacent-layer relationships, `normalizedMapSuffix(mapId)`.

- [ ] **Step 1: Add ID and count tests**

```js
test("map ledger is the final 46 groups and 171 maps", () => {
  assert.equal(new Set(maps.map(x => x.groupId)).size, 46);
  assert.equal(maps.length, 171);
  assert.equal(new Set(maps.map(x => x.mapId.toUpperCase())).size, 171);
  assert.equal(new Set(maps.map(x => x.donorId.toLowerCase())).size, 171);
});

test("missing size count is exactly 65", () => {
  assert.equal(maps.filter(x => x.width == null || x.height == null).length, 65);
});
```

- [ ] **Step 2: Verify failure before data exists**

Run: `node --test tools/game-design/test/ids.test.mjs`  
Expected: FAIL because `maps.json` does not exist.

- [ ] **Step 3: Encode all map rows**

Each row uses:

```json
{
  "continentId": 9,
  "groupId": "C09-G02",
  "groupName": "高原矿脉",
  "layer": 2,
  "mapId": "XX821",
  "donorId": "vx271",
  "displayName": "黄金矿道",
  "deploymentState": "阻断部署",
  "blockers": ["第9大陆传送坐标未提供"],
  "resolvedIdCollision": "褪色旅人战靴来源编号821已改配6407，待回写旧制式装备表"
}
```

Use `风暴断崖`, never `风暴断礁`. Never create a blocker from missing map dimensions. Only the exact relationship or placement lacking a real coordinate may be marked `阻断部署`.

- [ ] **Step 4: Encode connection rows inside `maps.json`**

Store `connections` alongside `maps`. Preserve the 91 complete C1—C8 relationships. Store the three partial relationships with exact missing fields, and store the 31 C9—C10 adjacent-layer relationships with all coordinate fields `null` and state `阻断部署`.

- [ ] **Step 5: Run map tests**

Run: `node --test tools/game-design/test/ids.test.mjs`  
Expected: PASS for counts and uniqueness; a separate assertion must verify the locked mappings `821→6407`、`823→6401`、`824→6403` and confirm their intersection with all 171 map suffixes is empty.

- [ ] **Step 6: Commit when authorized**

```bash
git add -- tools/game-design/test/ids.test.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/maps.json"
git commit -m "feat: add final 171-map audit ledger"
```

### Task 4: Build the 553-monster identity and numeric catalog

**Files:**
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/monsters.json`
- Create: `tools/game-design/test/monsters.test.mjs`

**Interfaces:**
- Consumes: `continents.json`, `maps.json`, the existing 36 C1 and 61 C2 stable monster identities, and `monsterHp()`.
- Produces: 553 normalized monster rows and `groupProgressionFactor(groupIndex,groupCount)`.

- [ ] **Step 1: Add exact count and relationship tests**

```js
test("ten continents contain 553 stable monster identities", () => {
  assert.equal(monsters.length, 553);
  assert.equal(monsters.filter(x => x.continentId === 1).length, 36);
  assert.equal(monsters.filter(x => x.continentId === 2).length, 61);
  assert.equal(monsters.filter(x => x.continentId >= 3).length, 456);
});

test("C3-C10 use twelve identities per map group", () => {
  for (const group of groups.filter(x => x.continentId >= 3)) {
    const rows = monsters.filter(x => x.groupId === group.groupId);
    assert.equal(rows.length, 12);
    assert.equal(rows.filter(x => x.type === "normal").length, 6);
    assert.equal(rows.filter(x => x.type === "rare").length, 4);
    assert.equal(rows.filter(x => ["map_boss","gate_boss"].includes(x.type)).length, 2);
  }
});

test("every monster has exactly one primary exclusive", () => {
  assert.ok(monsters.every(x => x.primaryExclusiveId && x.primaryExclusiveCount === 1));
});
```

- [ ] **Step 2: Verify failure before the catalog exists**

Run: `node --test tools/game-design/test/monsters.test.mjs`  
Expected: FAIL because `monsters.json` does not exist.

- [ ] **Step 3: Preserve C1/C2 identities without preserving values**

Import C1's 36 and C2's 61 names, IDs, model numbers, maps, layers, type/color and primary-exclusive relation. Set every imported numeric combat field's source to `TEN-CONTINENT-V1`; do not copy old HP, attack, defense, experience or drop denominators.

- [ ] **Step 4: Generate the 456 C3-C10 identities**

For each of the 38 groups create six normal roles, four rare roles and two BOSS roles. Use the group's actual display name plus a continent-specific lexicon; reject names ending in digits or matching `/怪物\d+|普通怪|稀有怪|BOSS\d+/`. The final group in each continent replaces its second map-BOSS role with `gate_boss`.

Use exact IDs:

```js
const typeCode = {normal:"N",rare:"R",map_boss:"B",gate_boss:"G"};
const monsterId = ({continentId,groupIndex,type,index}) =>
  `EL-MON-C${String(continentId).padStart(2,"0")}-G${String(groupIndex).padStart(2,"0")}-${typeCode[type]}${String(index).padStart(2,"0")}`;
```

- [ ] **Step 5: Apply the numeric mother line**

```js
const SCALE = 10_000n;

export function groupProgressionFactorFixed(i,n) {
  if (n === 1) return SCALE;
  return 6_500n + (3_500n * BigInt(i - 1) + BigInt(n - 1) / 2n) / BigInt(n - 1);
}

function plannedHp(monster,continent) {
  if (monster.type === "gate_boss") return monsterHp(continent.id,"gate_boss");
  const base = monsterHp(continent.id,monster.type);
  return base * groupProgressionFactorFixed(monster.groupIndex,continent.mapGroups) / SCALE;
}
```

All large HP calculations remain BigInt; never coerce them to `Number`.

- [ ] **Step 6: Separate design counts from coordinate installation**

Generate monster identities, numeric attributes and target spawn counts for every map without reading map dimensions. Derive target counts from layer/type and target KPH. Keep only `spawnX` and `spawnY` null until real walkability tests select coordinates; missing dimensions must never change the object's design status.

- [ ] **Step 7: Run tests**

Run: `node --test tools/game-design/test/monsters.test.mjs`  
Expected: PASS with 553 unique IDs, 553 unique names, valid model IDs and 553 primary-exclusive links.

- [ ] **Step 8: Commit when authorized**

```bash
git add -- tools/game-design/test/monsters.test.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/monsters.json"
git commit -m "feat: add ten-continent monster identity catalog"
```

### Task 5: Preserve eight tasks and create the new title/NPC model

**Files:**
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/preserved_tasks.json`
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/titles_npcs.json`
- Modify: `tools/game-design/test/model.test.mjs`

**Interfaces:**
- Consumes: task names, C1 NPC/story, C2 material relations, title names/costs and NPC dialogue from the spec.
- Produces: 8 protected task rows, 50 title-stage rows, 27 NPC/side-task rows, `allocateStageTotals(total)`.

- [ ] **Step 1: Add preservation and title allocation tests**

```js
test("all eight tasks survive without direct resilience or execute rewards", () => {
  assert.equal(tasks.length, 8);
  assert.deepEqual(tasks.map(x => x.name), [
    "海岸亡魂","风暴遗誓","沉王终曲","墓火归乡",
    "关隘断旗","雾林祖魂","踏碎风暴","接肢王座的终结"
  ]);
  assert.ok(tasks.every(x => x.preserveFlag === true));
  assert.ok(tasks.every(x => x.directResilience === 0 && x.directExecutePct === 0));
});

test("five title stages preserve the exact continent total", () => {
  assert.deepEqual(allocateStageTotals(7), [1,1,1,2,2]);
  assert.equal(allocateStageTotals(80).reduce((a,b) => a+b, 0), 80);
});
```

- [ ] **Step 2: Implement deterministic stage allocation**

```js
export function allocateStageTotals(total) {
  const shares = [0.10,0.15,0.20,0.25,0.30];
  const out = shares.map((x,i) => i < 4 ? Math.round(total * x) : 0);
  out[4] = total - out.slice(0,4).reduce((a,b) => a+b,0);
  return out;
}
```

- [ ] **Step 3: Encode the eight preserved tasks**

Each row must contain old and new reward fields. For example:

```json
{
  "taskId": "C02-T05",
  "name": "接肢王座的终结",
  "continentId": 2,
  "mapId": null,
  "mapGroup": "史东薇尔王城",
  "npcName": null,
  "preserveFlag": true,
  "oldReward": "接肢弑王；永久处决概率+2%",
  "newReward": "接肢王印×1；本大陆2小时货币；第二大陆纪念宝箱",
  "directResilience": 0,
  "directExecutePct": 0,
  "deploymentState": "阻断部署",
  "blockers": ["具体子地图未确定", "NPC名称未提供", "NPC坐标未提供"]
}
```

- [ ] **Step 4: Encode 50 title stages and NPC dialogue**

Use the exact title names, total resilience, drop increments and five-stage costs from the spec. Every NPC row includes `continentId,mapId,mapGroup,npcName,npcType,dialogue,materials,currency,reward,deploymentState,blockers`.

- [ ] **Step 5: Run tests**

Run: `node --test tools/game-design/test/model.test.mjs`  
Expected: PASS.

- [ ] **Step 6: Commit when authorized**

```bash
git add -- tools/game-design/model.mjs tools/game-design/test/model.test.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/preserved_tasks.json" "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/titles_npcs.json"
git commit -m "feat: preserve tasks and add continent title tracks"
```

### Task 6: Encode eleven strong synthesis items and recipes

**Files:**
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/synthesis.json`
- Modify: `tools/game-design/test/model.test.mjs`

**Interfaces:**
- Consumes: exact items, slots, fixed core affixes and maximum-drop allocations from the spec.
- Produces: 11 `equipment` rows and 11 `recipes` rows.

- [ ] **Step 1: Add recipe invariants**

```js
test("strong synthesis uses eleven unique slots", () => {
  assert.equal(synthesis.equipment.length, 11);
  assert.equal(new Set(synthesis.equipment.map(x => x.slot)).size, 11);
});

test("C3-C10 each has one or two items and recipes are local", () => {
  for (let c=3; c<=10; c++) {
    const count = synthesis.equipment.filter(x => x.continentId === c).length;
    assert.ok(count >= 1 && count <= 2);
  }
  synthesis.recipes.forEach(validateRecipe);
});

test("every result is at least forty percent above consumed same-slot boss item", () => {
  for (const item of synthesis.equipment) assert.ok(item.powerBudget >= item.strongestConsumedPowerBudget * 1.4);
});
```

- [ ] **Step 2: Verify failure**

Run: `node --test tools/game-design/test/model.test.mjs`  
Expected: FAIL because `synthesis.json` does not exist.

- [ ] **Step 3: Encode all eleven rows**

Use unique IDs `EL-SYN-C03-01` through `EL-SYN-C10-02`. Fixed core affixes are stored in `fixedAffixes`; secondary wash options are stored separately in `secondaryAffixPool`. Set `successRate=1`, `crossContinentInputs=0`, and `numericVersion="TEN-CONTINENT-V1"`.

- [ ] **Step 4: Encode recipe inputs**

For a one-item continent use exact quantities `1 boss same-slot + 1 boss/core + 2 non-boss same-slot + 360 common + 24 rare + 6 currency-hours`. For C4/C7/C10 split non-BOSS materials and currency 60%/40%, but keep each recipe's two required BOSS roles intact.

- [ ] **Step 5: Run tests**

Run: `node --test tools/game-design/test/model.test.mjs`  
Expected: PASS.

- [ ] **Step 6: Commit when authorized**

```bash
git add -- tools/game-design/test/model.test.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/synthesis.json"
git commit -m "feat: add local boss-driven synthesis recipes"
```

### Task 7: Build the equipment source ledger and remove cross-namespace conflicts

**Files:**
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/equipment_source_ledger.json`
- Modify: `tools/game-design/test/ids.test.mjs`

**Interfaces:**
- Consumes: all non-empty `来源编号` values from current equipment XLSX files and all 171 map IDs.
- Produces: canonical source-number ledger, `chooseUnusedSource(slot,allowedRanges,occupied,mapSuffixes)`.

- [ ] **Step 1: Add conflict tests**

```js
test("numeric map suffix never equals an equipment source number", () => {
  const mapSuffixes = new Set(maps.map(x => Number(x.mapId.slice(2))));
  const conflicts = ledger.filter(x => mapSuffixes.has(Number(x.sourceNumber)));
  assert.deepEqual(conflicts, []);
});
```

- [ ] **Step 2: Verify the test reports the three known conflicts**

Run: `node --test tools/game-design/test/ids.test.mjs`  
Expected: FAIL listing equipment source numbers 821, 823 and 824.

- [ ] **Step 3: Implement deterministic same-slot reassignment**

```js
export function chooseUnusedSource(slot, candidates, occupied, mapSuffixes) {
  const next = candidates
    .filter(x => x.slot === slot)
    .map(x => Number(x.sourceNumber))
    .sort((a,b) => a-b)
    .find(x => !occupied.has(x) && !mapSuffixes.has(x));
  if (next == null) throw new Error(`部位${slot}没有可用来源编号`);
  return next;
}
```

Use only same-slot resource candidates from the verified legal ranges. Record `oldSourceNumber,newSourceNumber,reason,evidenceFile` for 褪色旅人战靴、褪色旅人项链、褪色旅人戒指. Do not guess a source code outside the resource index.

- [ ] **Step 4: Re-run the tests**

Run: `node --test tools/game-design/test/ids.test.mjs`  
Expected: PASS with zero source duplicates and zero normalized map/source conflicts.

- [ ] **Step 5: Commit when authorized**

```bash
git add -- tools/game-design/test/ids.test.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/data/equipment_source_ledger.json"
git commit -m "fix: remove map and equipment source collisions"
```

### Task 8: Generate the five XLSX workbooks

**Files:**
- Create: `tools/game-design/build-workbooks.mjs`
- Create: the five XLSX files listed in File Map.

**Interfaces:**
- Consumes: all seven normalized JSON files and `model.mjs`.
- Produces: five styled XLSX files with formulas, frozen headers, filters, validations and status color rules.

- [ ] **Step 1: Mark spreadsheet authoring started once**

Run:

```bash
node container_tools/mark_artifact_operation_started.mjs --operation-kind create --expected-output-count 5 --output-format xlsx
```

Expected: command exits 0 before the first workbook creation call.

- [ ] **Step 2: Implement shared workbook formatting**

```js
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

function addHeader(sheet, address, values) {
  const range = sheet.getRange(address);
  range.values = [values];
  range.format = {
    fill: "#243447",
    font: { bold: true, color: "#FFFFFF", typeface: "Microsoft YaHei" },
    wrapText: true,
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#CBD5E1" }
  };
}
```

Use dark navy headers, gold section accents, pale blue formula cells, pale amber blocker cells, pale green verified cells, Chinese font `Microsoft YaHei`, and no merged cells inside data tables.

- [ ] **Step 3: Build `01_十大陆联合成长与爆率总表.xlsx`**

Sheets: `使用说明、十大陆总曲线、玩家快照、爆率产出模型、韧性称号总线、校验`.

The drop model sheet must use formulas equivalent to:

```excel
=MIN(1,[@人物倍数]*[@基础分子]/[@基础分母])
=IF([@掉落类型]="池",MIN(1,[@人物倍数]*[@池触发概率])*[@权重]/[@池总权重],[@有效概率])
=MIN([@战斗KPH],[@供给KPH])*[@最终概率]*[@平均数量]
```

- [ ] **Step 4: Build the remaining four workbooks**

- `02_十大陆怪物重做母表.xlsx`: `字段说明、怪物身份、强度母线、怪物导入表、击杀效率、掉落关联、校验`.
- `03_十大陆装备与合成总表.xlsx`: `字段说明、装备导入67列、规范化装备、强合成装备、配方、配方输入、来源编号账本、综合价值校验`.
- `04_NPC任务称号与对话总表.xlsx`: `字段说明、保留任务、新奖励替代、50档称号、NPC投放、完整对白、材料消耗、校验`.
- `05_地图传送与编号审计.xlsx`: `十大陆汇总、171地图、125组内连接、坐标缺口、编号冲突、部署门禁`；不生成地图尺寸缺口门禁。

- [ ] **Step 5: Export once per workbook**

Use `SpreadsheetFile.exportXlsx(workbook)` and save only after all sheets and formulas are complete. Do not repeatedly export during construction.

- [ ] **Step 6: Commit generator and workbooks when authorized**

```bash
git add -- tools/game-design/build-workbooks.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/01_十大陆联合成长与爆率总表.xlsx" "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/02_十大陆怪物重做母表.xlsx" "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/03_十大陆装备与合成总表.xlsx" "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/04_NPC任务称号与对话总表.xlsx" "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/05_地图传送与编号审计.xlsx"
git commit -m "feat: generate ten-continent design workbooks"
```

### Task 9: Update the six core archive files with explicit replacement history

**Files:**
- Create: `tools/game-design/update-core-archive.mjs`
- Create: `tools/game-design/test/archive.test.mjs`
- Modify: the six core archive files listed in File Map.

**Interfaces:**
- Consumes: normalized JSON, generated workbook paths and current six-file archive.
- Produces: current effective archive without superseded plans.

- [ ] **Step 1: Write archive red-flag tests**

```js
const forbiddenInCurrent = [
  "13大陆主线顺序已经锁定",
  "圣树分支",
  "法姆·亚兹拉",
  "永恒之城",
  "前4个任务各奖励永久韧性20",
  "最终任务奖励永久处决概率2%",
  "现有怪物属性保留，不整体重做",
  "漂流群岛不部署任何功能性NPC"
];

test("current effective design contains no superseded rules", async () => {
  const current = await fs.readFile(CURRENT_DESIGN, "utf8");
  for (const phrase of forbiddenInCurrent) assert.equal(current.includes(phrase), false, phrase);
});
```

- [ ] **Step 2: Run tests and verify failure on the old archive**

Run: `node --test tools/game-design/test/archive.test.mjs`  
Expected: FAIL and list old 13-continent/task/monster phrases.

- [ ] **Step 3: Update `00_项目总纲.md` and `05_当前有效游戏设计总档.md`**

Replace the old continent section with the 10-continent order and `46组/171图`. Replace the old task-resilience loop with the separate task/title systems. Replace the old C1/C2 retention statement with “names/models/stories retained; numeric fields rebuilt.” Add the local-only drop model, 100x curve, 11 synthesis items and current map blockers.

- [ ] **Step 4: Update `03_变更记录.md`**

Add one row per replacement category with exact columns `原方案、替代方案、保留内容、影响文件、状态`. The categories are: 13→10 continents, C1/C2 numeric rebuild, soul-title decoupling, preserved task reward replacement, C3+ synthesis, 100x local drop calibration, clothing resilience, map/source collisions.

- [ ] **Step 5: Update `04_每日设计更新.md` and `01_当前任务指针.txt`**

Append one 2026-08-20 entry only. The pointer's next action must be: generate/verify the five workbooks, then fill the exact map/NPC/connection coordinates; it must not claim deployment.

- [ ] **Step 6: Update `02_已确认规则与数值.xlsx`**

Add or replace rows in `已确认规则、数值参数、地图索引、怪物索引、装备索引、掉落索引`. Preserve historical rows only where the workbook has an explicit historical sheet; current sheets must contain only active 10-continent rules.

- [ ] **Step 7: Run archive tests**

Run: `node --test tools/game-design/test/archive.test.mjs`  
Expected: PASS. The change log may contain the names of removed continents only inside `原方案`/historical cells.

- [ ] **Step 8: Commit when authorized**

```bash
git add -- tools/game-design/update-core-archive.mjs tools/game-design/test/archive.test.mjs "传奇私服之旅/艾尔登法环项目档案/00_项目总纲.md" "传奇私服之旅/艾尔登法环项目档案/01_当前任务指针.txt" "传奇私服之旅/艾尔登法环项目档案/02_已确认规则与数值.xlsx" "传奇私服之旅/艾尔登法环项目档案/03_变更记录.md" "传奇私服之旅/艾尔登法环项目档案/04_每日设计更新.md" "传奇私服之旅/艾尔登法环项目档案/05_当前有效游戏设计总档.md"
git commit -m "docs: adopt ten-continent authoritative design"
```

### Task 10: Run full validation, formula scan and visual review

**Files:**
- Create: `tools/game-design/validate-design.mjs`
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/validation/report.json`
- Create: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/validation/previews/*.png`

**Interfaces:**
- Consumes: all JSON, XLSX and six core files.
- Produces: machine-readable pass/fail report and rendered previews.

- [ ] **Step 1: Implement the full validator**

The report must contain exact counters:

```json
{
  "continents": 10,
  "mapGroups": 46,
  "maps": 171,
  "mapIdDuplicates": 0,
  "donorIdDuplicates": 0,
  "sourceIdDuplicates": 0,
  "normalizedMapSourceConflicts": 0,
  "missingMapSizes": 65,
  "blockedC1ToC8Connections": 3,
  "blockedC9ToC10Connections": 31,
  "preservedTasks": 8,
  "titleStages": 50,
  "npcPlanRows": 27,
  "monsters": 553,
  "strongSynthesisItems": 11,
  "formulaErrors": 0
}
```

Treat the 65 missing sizes and 34 blocked connections as known blockers, not validation failures; validation fails only if they are omitted, miscounted or mislabeled as deployable.

- [ ] **Step 2: Run all Node tests**

Run: `node --test tools/game-design/test/*.test.mjs`  
Expected: all tests PASS.

- [ ] **Step 3: Run the design validator**

Run: `node tools/game-design/validate-design.mjs`  
Expected: exit 0 and write `validation/report.json` with the exact counters above.

- [ ] **Step 4: Render every workbook sheet**

Render all five workbooks to `validation/previews/`; inspect title rows, headers, wrapped dialogue, formulas, conditional status colors, clipping and blank trailing regions. Fix all visual defects before continuing.

- [ ] **Step 5: Scan formulas**

Use artifact inspection with matches for `#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A`.  
Expected: zero matches across all five workbooks and the updated rules workbook.

- [ ] **Step 6: Inspect the final Git diff without staging unrelated work**

Run:

```bash
git status --short
git diff --stat
git diff -- "传奇私服之旅/艾尔登法环项目档案" tools/game-design docs/superpowers
```

Expected: only this plan/spec, `tools/game-design`, the new ten-continent directory and the six core files are changed.

- [ ] **Step 7: Commit validation evidence when authorized**

```bash
git add -- tools/game-design/validate-design.mjs "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/validation/report.json" "传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/validation/previews"
git commit -m "test: validate ten-continent design package"
```

### Task 11: Prepare the Codex handoff without claiming deployment

**Files:**
- Modify: `传奇私服之旅/艾尔登法环项目档案/游戏设计/十大陆联合重做/00_Codex执行总说明.md`

**Interfaces:**
- Consumes: validation report and final Git state.
- Produces: a concise handoff with completed artifacts, known blockers and the next executable action.

- [ ] **Step 1: Write the final handoff status**

The handoff must say:

- design package generated and validated;
- maps are planned, not deployed;
- exact blockers are 65 missing sizes, three partial C1—C8 connections, 31 C9—C10 connections without coordinates, undefined inter-group/inter-continent portals, and all new NPC coordinates;
- source-number conflicts 821/823/824 have been reassigned with evidence in the ledger;
- no server, M2, database or live map operation occurred.

- [ ] **Step 2: Record the next action**

The only next action is to read actual MAP walkability data, fill sizes and coordinates, then run a separate deployment preflight. Monster/equipment database import must wait until this design package is reviewed and the source ledger passes again against the target server.

- [ ] **Step 3: Final verification**

Run:

```bash
node --test tools/game-design/test/*.test.mjs
node tools/game-design/validate-design.mjs
git status --short
```

Expected: tests and validator pass; status contains only intended files. Do not push, create a PR or merge unless the user separately authorizes that exact action.
