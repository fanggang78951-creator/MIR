import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = process.cwd();
const outputRoot = path.join(
  root,
  "outputs/elden_ring_10_continent_actual_data_20260820",
);
const c1Root = path.join(outputRoot, "C01_漂流群岛");

function readJson(filePath) {
  assert.equal(fs.existsSync(filePath), true, `missing artifact: ${filePath}`);
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

test("global ledger keeps all ten continents in one ordered authority", () => {
  const ledger = readJson(path.join(outputRoot, "data/global_ledger.json"));
  assert.equal(ledger.continents.length, 10);
  assert.deepEqual(
    ledger.continents.map((item) => item.id),
    ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10"],
  );
  assert.equal(ledger.rules.mapSizeRequired, false);
  assert.equal(ledger.continents[0].monsterCount, 36);
  assert.equal(ledger.continents[0].primaryExclusiveCount, 36);
  assert.deepEqual(
    ledger.idConflictResolutions.map((item) => [item.mapId, item.oldSourceNumber, item.newSourceNumber]),
    [["XX821", 821, 6407], ["XX823", 823, 6401], ["XX824", 824, 6403]],
  );
  assert.equal(new Set(ledger.idConflictResolutions.map((item) => item.newSourceNumber)).size, 3);
});

test("first continent has 36 unique and numerically complete monsters", () => {
  const monsters = readJson(path.join(c1Root, "data/monsters.json"));
  assert.equal(monsters.length, 36);
  assert.equal(new Set(monsters.map((item) => item.id)).size, 36);
  assert.equal(new Set(monsters.map((item) => item.name)).size, 36);
  assert.deepEqual(
    monsters.reduce((acc, item) => {
      acc[item.type] = (acc[item.type] ?? 0) + 1;
      return acc;
    }, {}),
    { normal: 17, rare: 12, boss: 6, gate_boss: 1 },
  );
  for (const monster of monsters) {
    assert.match(monster.mapId, /^XX\d+$/);
    for (const key of ["level", "experience", "hp", "defense", "magicDefense", "minAttack", "maxAttack", "accuracy"]) {
      assert.equal(Number.isInteger(monster[key]), true, `${monster.name}.${key}`);
      assert.equal(monster[key] >= 0, true, `${monster.name}.${key}`);
    }
    assert.equal(monster.minAttack <= monster.maxAttack, true, monster.name);
    assert.equal(typeof monster.primaryExclusiveId, "string", monster.name);
  }
  const gate = monsters.find((item) => item.type === "gate_boss");
  assert.equal(gate.name, "沉没之王·奥德里安");
  assert.equal(gate.hp, 10_000_000);
});

test("first continent has 36 primary exclusives plus two gate-boss fashion extras", () => {
  const monsters = readJson(path.join(c1Root, "data/monsters.json"));
  const equipment = readJson(path.join(c1Root, "data/equipment.json"));
  assert.equal(equipment.length, 38);
  assert.equal(new Set(equipment.map((item) => item.id)).size, 38);
  assert.equal(new Set(equipment.map((item) => item.name)).size, 38);
  assert.equal(equipment.filter((item) => item.primaryExclusive).length, 36);
  assert.equal(equipment.filter((item) => item.extraGateDrop).length, 2);
  assert.equal(
    monsters.every((monster) => equipment.some((item) => item.id === monster.primaryExclusiveId)),
    true,
  );
  for (const item of equipment) {
    assert.equal(item.importRow.length, 67, `${item.name} import field count`);
    assert.equal(item.importRow[0], item.name);
    assert.equal(item.importRow[1], item.slot);
  }
  const sourceNumbers = equipment.map((item) => item.sourceNumber).filter((value) => value !== null);
  assert.equal(new Set(sourceNumbers).size, sourceNumbers.length);
  assert.equal(sourceNumbers.some((value) => [113, 112, 330, 327, 328, 329, 106, 102, 103, 104, 105].includes(Number(value))), false);
});

test("first-continent graduation equipment contributes exactly 150 percent max-drop budget", () => {
  const equipment = readJson(path.join(c1Root, "data/equipment.json"));
  const graduation = equipment.filter((item) => item.graduationLoadoutCount > 0);
  const total = graduation.reduce(
    (sum, item) => sum + item.maxDropRate * item.graduationLoadoutCount,
    0,
  );
  assert.equal(total, 150);
});

test("first continent contains exact drop rows and one MonItems file per monster", () => {
  const drops = readJson(path.join(c1Root, "data/drops.json"));
  const monsters = readJson(path.join(c1Root, "data/monsters.json"));
  assert.equal(drops.length, 36);
  assert.equal(new Set(drops.map((item) => item.monsterId)).size, 36);
  for (const drop of drops) {
    const monster = monsters.find((item) => item.id === drop.monsterId);
    const exclusive = drop.items.find((item) => item.role === "primary_exclusive");
    assert.equal(Boolean(exclusive), true, monster.name);
    const expected = {
      normal: 1800,
      rare: 600,
      boss: 120,
      gate_boss: 50,
    }[monster.type];
    assert.equal(exclusive.denominator, expected, monster.name);
  }
  const monItemsDir = path.join(c1Root, "怪物爆率/MonItems_GBK");
  assert.equal(fs.readdirSync(monItemsDir).filter((name) => name.endsWith(".txt")).length, 36);
});

test("four first-continent NPC files preserve tasks without old direct resilience rewards", () => {
  const npcs = readJson(path.join(c1Root, "data/npcs.json"));
  assert.equal(npcs.length, 4);
  assert.deepEqual(
    npcs.map((item) => item.name),
    ["拾骸女·梅芙", "断誓骑士·罗恩", "无冠史官·塞蕾", "渡海铭誓官·伊莱恩"],
  );
  for (const npc of npcs) {
    assert.match(npc.mapId, /^XX\d+$/);
    assert.equal(npc.coordinate, null);
    assert.equal(npc.deploymentState, "待选坐标");
    const text = JSON.stringify(npc);
    assert.equal(text.includes("韧性+20"), false);
    assert.equal(text.includes("永久处决"), false);
  }
  const npcDir = path.join(c1Root, "NPC设计");
  assert.equal(fs.readdirSync(npcDir).filter((name) => name.endsWith(".txt")).length, 4);
});

test("engine-facing workbooks and readable ledgers are present", () => {
  for (const relativePath of [
    "00_十大陆全局设计总账.xlsx",
    "C01_漂流群岛/20_怪物批量生成_漂流群岛重做.xlsx",
    "C01_漂流群岛/09_装备批量生成_漂流群岛专属重做.xlsx",
    "C01_漂流群岛/01_第一大陆数值与掉落校准表.xlsx",
    "C01_漂流群岛/第一大陆_怪物掉落总览_UTF8.txt",
  ]) {
    assert.equal(fs.existsSync(path.join(outputRoot, relativePath)), true, relativePath);
  }
});
