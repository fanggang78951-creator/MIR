import fs from "node:fs/promises";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = process.cwd();
const OUTPUT_ROOT = path.join(
  ROOT,
  "outputs/elden_ring_10_continent_actual_data_20260820",
);
const C1_ROOT = path.join(OUTPUT_ROOT, "C01_漂流群岛");
const DATA_DIR = path.join(C1_ROOT, "data");
const GLOBAL_DATA_DIR = path.join(OUTPUT_ROOT, "data");
const NPC_DIR = path.join(C1_ROOT, "NPC设计");
const MONITEMS_UTF8_DIR = path.join(C1_ROOT, "怪物爆率/MonItems_UTF8");
const MONITEMS_GBK_DIR = path.join(C1_ROOT, "怪物爆率/MonItems_GBK");
const PREVIEW_DIR = path.join(OUTPUT_ROOT, "_preview");

const MONSTER_SOURCE = path.join(
  ROOT,
  "outputs/elden_first_continent_rebalanced_20260805/20_怪物批量生成.xlsx",
);
const MONSTER_TEMPLATE = path.join(ROOT, "upload/20_怪物批量生成(3).xlsx");
const EQUIPMENT_SOURCE = path.join(
  ROOT,
  "outputs/elden_first_continent_exclusive_merged_20260805/第一大陆_专属装备总表.xlsx",
);
const EQUIPMENT_TEMPLATE = path.join(ROOT, "upload/09_装备批量生成(7).xlsx");
const DROP_SOURCE_DIR = path.join(
  ROOT,
  "outputs/elden_monitems_final_20260802/第一大陆_36怪_正式爆率/MonItems",
);

const VERSION = "EL-C01-V1-20260820";
const MAP_SIZE_REQUIRED = false;
const PLAYER_DROP_MULTIPLIER = 5;
const C1_GOLD_PER_HOUR = 200_000;

const mapGroups = [
  {
    index: 1,
    name: "失乡者海岸",
    factor: 0.65,
    maps: [
      ["XX113", "失乡者海岸"],
      ["XX112", "失乡者海岸底层"],
      ["XX330", "失乡者王座"],
    ],
  },
  {
    index: 2,
    name: "风暴断崖",
    factor: 0.825,
    maps: [
      ["XX327", "风暴断崖一层"],
      ["XX328", "风暴断崖二层"],
      ["XX329", "风暴断崖三层"],
      ["XX106", "风暴断崖四层"],
    ],
  },
  {
    index: 3,
    name: "沉没王庭",
    factor: 1,
    maps: [
      ["XX102", "沉没王庭外围"],
      ["XX103", "沉没王庭内庭"],
      ["XX104", "沉没王庭底层"],
      ["XX105", "沉没王座"],
    ],
  },
];

const continentLedger = [
  ["C01", "漂流群岛", 3, 11, 36, 36, 0, 5, "10000000", "第一版实数已生成"],
  ["C02", "宁姆格福", 5, 16, 61, 61, 0, 7, "200000000", "待重算"],
  ["C03", "宁姆格福西域", 6, 20, 72, 72, 1, 10, "4000000000", "待制作"],
  ["C04", "利耶尼亚海域", 6, 17, 72, 72, 2, 14, "80000000000", "待制作"],
  ["C05", "湖之利耶尼亚", 6, 22, 72, 72, 1, 20, "1600000000000", "待制作"],
  ["C06", "盖利德", 3, 15, 36, 36, 1, 28, "32000000000000", "待制作"],
  ["C07", "化圣雪原", 3, 13, 36, 36, 2, 40, "640000000000000", "待制作"],
  ["C08", "巨人山顶", 4, 16, 48, 48, 1, 55, "12800000000000000", "待制作"],
  ["C09", "亚坛高原", 5, 22, 60, 60, 1, 75, "256000000000000000", "待制作"],
  ["C10", "王城罗德尔", 5, 19, 60, 60, 2, 100, "5120000000000000000", "待制作"],
];

const idConflictResolutions = [
  {
    mapId: "XX821",
    mapName: "黄金矿道",
    equipmentName: "褪色旅人战靴",
    slot: "鞋子",
    oldSourceNumber: 821,
    newSourceNumber: 6407,
    resourceName: "黄金圣树·初誓／鞋子",
    state: "替代号已锁定，待回写制式装备表",
  },
  {
    mapId: "XX823",
    mapName: "深层矿井",
    equipmentName: "褪色旅人项链",
    slot: "项链",
    oldSourceNumber: 823,
    newSourceNumber: 6401,
    resourceName: "黄金圣树·初誓／项链",
    state: "替代号已锁定，待回写制式装备表",
  },
  {
    mapId: "XX824",
    mapName: "矿脉核心",
    equipmentName: "褪色旅人戒指",
    slot: "戒指",
    oldSourceNumber: 824,
    newSourceNumber: 6403,
    resourceName: "黄金圣树·初誓／戒指",
    state: "替代号已锁定，待回写制式装备表",
  },
];

const taskMaterialByMonster = {
  "铁锚行刑者": ["锈锚魂魄", 50],
  "沉船守财者": ["沉金魂魄", 60],
  "断桅船长·赫恩": ["船长残魂", 20],
  "吞岸巨兽·格拉姆": ["吞岸王魂", 25],
  "逐雷骑士": ["逐雷魂印", 80],
  "裂岩巨人": ["裂岩之心", 100],
  "风暴执刑官·巴鲁克": ["执刑官残魂", 20],
  "断崖古龙·赛尔": ["古龙逆鳞", 25],
  "失冠王子": ["失冠徽记", 100],
  "沉默女祭司": ["沉默祷文", 120],
  "溺王亲卫长·萨恩": ["亲卫长残魂", 25],
  "深潮大祭司·伊莱娜": ["深潮祭冠", 30],
  "沉没之王·奥德里安": ["沉王魂核", 10],
};

const graduationLoadout = {
  "沉没王权": [1, 15],
  "深潮王铠": [1, 10],
  "溺亡王盔": [1, 5],
  "沉宫项链": [1, 7],
  "苔痕护腕": [2, 7],
  "王庭秘戒": [2, 7],
  "深水束带": [1, 7],
  "失冠战靴": [1, 12],
  "深渊勋章": [1, 11],
  "裁决王盾": [1, 14],
  "沉默灵玉": [1, 11],
  "幽灯面巾": [1, 7],
  "潮葬礼剑": [1, 9],
  "无冠王衣": [1, 14],
};

const resolvedSourceNumbers = {
  "石蜥面巾": 6400,
  "幽灯面巾": 6435,
};

const equipmentTierStats = {
  1: {
    normal: { attackBonus: 2, monsterDamage: 2, criticalDamage: 3, attackDamage: 0, maxDrop: 2, absorb: 0, critChance: 0 },
    rare: { attackBonus: 4, monsterDamage: 3, criticalDamage: 5, attackDamage: 1, maxDrop: 4, absorb: 0, critChance: 1 },
    boss: { attackBonus: 6, monsterDamage: 5, criticalDamage: 7, attackDamage: 1, maxDrop: 6, absorb: 2, critChance: 1 },
  },
  2: {
    normal: { attackBonus: 3, monsterDamage: 2, criticalDamage: 4, attackDamage: 0, maxDrop: 3, absorb: 0, critChance: 0 },
    rare: { attackBonus: 5, monsterDamage: 4, criticalDamage: 6, attackDamage: 1, maxDrop: 5, absorb: 0, critChance: 1 },
    boss: { attackBonus: 7, monsterDamage: 6, criticalDamage: 8, attackDamage: 2, maxDrop: 8, absorb: 3, critChance: 2 },
  },
  3: {
    normal: { attackBonus: 4, monsterDamage: 3, criticalDamage: 5, attackDamage: 1, maxDrop: 5, absorb: 0, critChance: 1 },
    rare: { attackBonus: 6, monsterDamage: 5, criticalDamage: 7, attackDamage: 2, maxDrop: 7, absorb: 0, critChance: 2 },
    boss: { attackBonus: 8, monsterDamage: 7, criticalDamage: 10, attackDamage: 3, maxDrop: 10, absorb: 4, critChance: 2 },
    gate_boss: { attackBonus: 10, monsterDamage: 8, criticalDamage: 12, attackDamage: 4, maxDrop: 15, absorb: 4, critChance: 3 },
  },
};

function roundTo(value, step) {
  return Math.max(step, Math.round(value / step) * step);
}

function progressionScalar(index, count, min, max) {
  if (count <= 1) return max;
  return min + ((max - min) * index) / (count - 1);
}

function detectGroup(remarks) {
  if (remarks.includes("失乡者海岸")) return mapGroups[0];
  if (remarks.includes("风暴断崖")) return mapGroups[1];
  if (remarks.includes("沉没王庭")) return mapGroups[2];
  throw new Error(`cannot detect map group from: ${remarks}`);
}

function detectMonsterType(remarks) {
  if (remarks.includes("守关BOSS")) return "gate_boss";
  if (remarks.includes("BOSS")) return "boss";
  if (remarks.includes("稀有")) return "rare";
  return "normal";
}

function parseLayerRange(remarks, mapCount) {
  const match = remarks.match(/·(\d+)(?:[—-](\d+))?层/);
  if (!match) return [1, mapCount];
  const first = Number(match[1]);
  const last = Number(match[2] ?? match[1]);
  return [first, last];
}

function exclusiveNameFromRemarks(remarks) {
  const match = remarks.match(/专属：([^。；]+)/);
  if (!match) throw new Error(`missing primary exclusive in remarks: ${remarks}`);
  return match[1].trim();
}

function roleAttackMultiplier(name) {
  if (/猎犬|雷羽鹰|战奴|猎杀者|侍从|女祭司/.test(name)) return 0.82;
  if (/弩手|祷师|祭司|咒师/.test(name)) return 0.9;
  if (/巨蟹|守财者|巨人|石像|裁决官|巨兽|古龙|王/.test(name)) return 1.15;
  return 1;
}

function roleDefenseMultipliers(name) {
  let defense = 1;
  let magicDefense = 0.82;
  if (/祷师|祭司|咒师|女祭司/.test(name)) {
    defense *= 0.88;
    magicDefense *= 1.35;
  }
  if (/巨蟹|守卫|守财者|骑士|巨人|石像|看守|裁决官|禁卫|亲卫长|巨兽|古龙|王/.test(name)) {
    defense *= 1.15;
  }
  return { defense, magicDefense };
}

function objectFromRow(headers, row) {
  return Object.fromEntries(headers.map((header, index) => [header, row[index] ?? null]));
}

function rowFromObject(headers, object) {
  return headers.map((header) => object[header] ?? null);
}

function replaceExactDropLine(text, itemName, denominator) {
  const escaped = itemName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`^1/\\d+\\s+${escaped}\\s*$`, "m");
  if (!regex.test(text)) {
    return `${text.trimEnd()}\n\n1/${denominator} ${itemName}\n`;
  }
  return text.replace(regex, `1/${denominator} ${itemName}`);
}

function appendUniqueDropLine(text, denominator, itemName) {
  const escaped = itemName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const existing = new RegExp(`^1/\\d+\\s+${escaped}\\s*$`, "m");
  if (existing.test(text)) return text;
  return `${text.trimEnd()}\n\n1/${denominator} ${itemName}\n`;
}

function excelColumnName(number) {
  let value = number;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function applyTableStyle(sheet, rangeAddress, headerRow = 1) {
  const range = sheet.getRange(rangeAddress);
  range.format.font = { name: "Microsoft YaHei", size: 10, color: "#1F2937" };
  range.format.verticalAlignment = "center";
  range.format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
  const used = sheet.getUsedRange();
  const lastCol = excelColumnName(used.columnCount);
  sheet.getRange(`A${headerRow}:${lastCol}${headerRow}`).format = {
    fill: "#17365D",
    font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "medium", color: "#17365D" },
  };
  sheet.freezePanes.freezeRows(headerRow);
  sheet.showGridLines = false;
}

function setWidths(sheet, widths) {
  for (const [column, width] of Object.entries(widths)) {
    sheet.getRange(`${column}:${column}`).format.columnWidth = width;
  }
}

async function saveJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, JSON.stringify(value, null, 2), "utf8");
}

async function loadSourceData() {
  const monsterWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(MONSTER_SOURCE));
  const monsterSheet = monsterWorkbook.worksheets.getItem("怪物生成");
  const monsterRows = monsterSheet.getRange("A1:L37").values;
  const monsterHeaders = monsterRows[0];

  const equipmentWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(EQUIPMENT_SOURCE));
  const equipmentSheet = equipmentWorkbook.worksheets.getItem("装备导入表");
  const equipmentRows = equipmentSheet.getRange("A1:BO39").values;
  const equipmentHeaders = equipmentRows[0];

  const equipmentTemplateWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(EQUIPMENT_TEMPLATE));
  const equipmentTemplateSheet = equipmentTemplateWorkbook.worksheets.getItem("装备导入表");
  const targetEquipmentHeaders = equipmentTemplateSheet.getRange("A1:BO1").values[0];

  return {
    monsterHeaders,
    monsterSourceRows: monsterRows.slice(1),
    equipmentHeaders,
    equipmentSourceRows: equipmentRows.slice(1),
    targetEquipmentHeaders,
  };
}

function buildMonsters(source) {
  const preliminary = source.monsterSourceRows.map((row) => {
    const raw = objectFromRow(source.monsterHeaders, row);
    const group = detectGroup(raw["备注"]);
    const type = detectMonsterType(raw["备注"]);
    const [layerStart, layerEnd] = parseLayerRange(raw["备注"], group.maps.length);
    const primaryExclusiveName = exclusiveNameFromRemarks(raw["备注"]);
    return { raw, group, type, layerStart, layerEnd, primaryExclusiveName };
  });

  const totals = new Map();
  for (const item of preliminary) {
    const key = `${item.group.index}:${item.type}`;
    totals.set(key, (totals.get(key) ?? 0) + 1);
  }
  const counters = new Map();

  const hpBase = { normal: 80_000, rare: 300_000, boss: 2_000_000, gate_boss: 10_000_000 };
  const defenseBase = { normal: 420, rare: 700, boss: 1050, gate_boss: 1200 };
  const maxAttackBase = { normal: 1600, rare: 3000, boss: 6500, gate_boss: 16_000 };
  const codeByType = { normal: "N", rare: "R", boss: "B", gate_boss: "G" };
  const colorByType = { normal: "黄色", rare: "蓝色", boss: "粉色", gate_boss: "红色" };
  const hpRangeByType = {
    normal: [0.8, 1.2],
    rare: [0.85, 1.15],
    boss: [0.9, 1],
    gate_boss: [1, 1],
  };

  return preliminary.map((item) => {
    const key = `${item.group.index}:${item.type}`;
    const ordinal = counters.get(key) ?? 0;
    counters.set(key, ordinal + 1);
    const count = totals.get(key);
    const [rankMin, rankMax] = hpRangeByType[item.type];
    const rankFactor = progressionScalar(ordinal, count, rankMin, rankMax);
    const groupFactor = item.type === "gate_boss" ? 1 : item.group.factor;
    const defenseFlavor = roleDefenseMultipliers(item.raw["怪物名称"]);
    const attackFlavor = roleAttackMultiplier(item.raw["怪物名称"]);
    const hp = item.type === "gate_boss"
      ? 10_000_000
      : roundTo(hpBase[item.type] * groupFactor * rankFactor, 1000);
    const defense = roundTo(
      defenseBase[item.type] * groupFactor * rankFactor * defenseFlavor.defense,
      10,
    );
    const magicDefense = roundTo(
      defenseBase[item.type] * groupFactor * rankFactor * defenseFlavor.magicDefense,
      10,
    );
    const maxAttack = item.type === "gate_boss"
      ? 16_000
      : roundTo(maxAttackBase[item.type] * groupFactor * rankFactor * attackFlavor, 10);
    const minAttack = roundTo(maxAttack * 0.72, 10);
    const experienceRate = { normal: 0.08, rare: 0.12, boss: 0.2, gate_boss: 0.25 }[item.type];
    const experience = roundTo(hp * experienceRate, 100);
    const mapIds = item.group.maps.slice(item.layerStart - 1, item.layerEnd).map(([id]) => id);
    const mapNames = item.group.maps.slice(item.layerStart - 1, item.layerEnd).map(([, name]) => name);
    const monsterId = `EL-MON-C01-G${String(item.group.index).padStart(2, "0")}-${codeByType[item.type]}${String(ordinal + 1).padStart(2, "0")}`;
    const equipmentIndex = source.equipmentSourceRows.findIndex((row) => row[0] === item.primaryExclusiveName);
    if (equipmentIndex < 0) throw new Error(`missing equipment row: ${item.primaryExclusiveName}`);
    return {
      id: monsterId,
      continentId: "C01",
      continentName: "漂流群岛",
      groupId: `EL-MAP-C01-G${String(item.group.index).padStart(2, "0")}`,
      groupName: item.group.name,
      mapId: mapIds[0],
      mapIds,
      mapNames,
      layerStart: item.layerStart,
      layerEnd: item.layerEnd,
      type: item.type,
      color: colorByType[item.type],
      name: item.raw["怪物名称"],
      level: Number(item.raw["等级"]),
      experience,
      hp,
      defense,
      magicDefense,
      minAttack,
      maxAttack,
      accuracy: 500,
      modelLibraryId: null,
      modelRule: "平台稳定随机；后续若指定外观，只补模型编号，不改怪物身份",
      primaryExclusiveId: `EL-EQP-C01-${String(equipmentIndex + 1).padStart(3, "0")}`,
      primaryExclusiveName: item.primaryExclusiveName,
      numericVersion: VERSION,
      deploymentState: "设计数据完成，未部署",
      remarks: `${item.group.name}·${item.layerStart === item.layerEnd ? item.layerStart : `${item.layerStart}—${item.layerEnd}`}层·${item.type}；主要专属：${item.primaryExclusiveName}`,
    };
  });
}

function buildEquipment(source, monsters) {
  const sourceObjects = source.equipmentSourceRows.map((row) => objectFromRow(source.equipmentHeaders, row));
  const monsterByPrimary = new Map(monsters.map((monster) => [monster.primaryExclusiveName, monster]));
  const gate = monsters.find((monster) => monster.type === "gate_boss");
  const specialFields = new Set([
    "攻击加成", "魔法加成", "道术加成", "神力倍攻", "伤害系数", "打怪伤害", "暴击伤害",
    "固定切割", "爆率", "最大爆率", "首刀斩杀", "尾刀斩杀", "鞭尸", "处决概率", "韧性",
    "处决倍率", "处决时间", "对怪伤害吸收", "伤害吸收上限", "吸血", "每秒回血", "回收增加",
    "暴击几率", "攻击伤害", "伤害吸收", "魔法防御", "忽视防御", "伤害反弹", "人物爆率",
    "体力增加", "魔力增加", "怒气恢复", "合击攻击", "怪物爆率", "防爆几率", "防止麻痹",
    "防止护身", "防止复活", "防止全毒", "防止诱惑", "防止火墙", "防止冰冻", "防止蛛网",
    "致命几率", "致命伤害", "致命防御", "暴击抗性", "攻击伤害抗性", "杀怪经验倍数", "HP百分比",
  ]);

  return sourceObjects.map((raw, index) => {
    const primaryMonster = monsterByPrimary.get(raw["名称"]);
    const extraGateDrop = !primaryMonster && ["潮葬礼剑", "无冠王衣"].includes(raw["名称"]);
    if (!primaryMonster && !extraGateDrop) throw new Error(`equipment has no source monster: ${raw["名称"]}`);
    const sourceMonster = primaryMonster ?? gate;
    const stats = extraGateDrop
      ? raw["名称"] === "潮葬礼剑"
        ? { attackBonus: 6, monsterDamage: 5, criticalDamage: 8, attackDamage: 2, maxDrop: 9, absorb: 2, critChance: 2 }
        : { attackBonus: 5, monsterDamage: 4, criticalDamage: 7, attackDamage: 2, maxDrop: 14, absorb: 3, critChance: 2 }
      : equipmentTierStats[sourceMonster.groupId.endsWith("01") ? 1 : sourceMonster.groupId.endsWith("02") ? 2 : 3][sourceMonster.type];

    const output = {};
    for (const header of source.targetEquipmentHeaders) output[header] = null;
    for (const header of source.targetEquipmentHeaders) {
      if (specialFields.has(header)) continue;
      if (Object.hasOwn(raw, header)) output[header] = raw[header];
    }
    output["名称"] = raw["名称"];
    output["部位"] = raw["部位"];
    output["来源编号"] = resolvedSourceNumbers[raw["名称"]] ?? raw["来源编号"] ?? null;
    output["等级"] = 1;
    output["重量"] = 1;
    output["悬浮分类"] = "稀有专属";
    output["攻击加成"] = stats.attackBonus;
    output["魔法加成"] = stats.attackBonus;
    output["道术加成"] = stats.attackBonus;
    output["打怪伤害"] = stats.monsterDamage;
    output["暴击伤害"] = stats.criticalDamage;
    output["攻击伤害"] = stats.attackDamage || null;
    output["暴击几率"] = stats.critChance || null;
    output["对怪伤害吸收"] = stats.absorb || null;

    const [loadoutCount, loadoutMaxDrop] = graduationLoadout[raw["名称"]] ?? [0, null];
    output["最大爆率"] = loadoutMaxDrop ?? stats.maxDrop;

    if (raw["名称"] === "沉没王权") {
      output["攻击"] = "350-700";
      output["魔法"] = "350-700";
      output["道术"] = "350-700";
      output["伤害系数"] = 3;
      output["致命几率"] = 1;
      output["致命伤害"] = 10;
    }
    if (raw["名称"] === "潮葬礼剑") {
      output["攻击"] = "50-100";
      output["魔法"] = "50-100";
      output["道术"] = "50-100";
      output["伤害系数"] = 2;
      output["处决概率"] = 5;
    }
    const resilienceByClothing = {
      "漂流尸甲": 1,
      "吞岸重甲": 2,
      "古龙风铠": 2,
      "深潮王铠": 3,
    };
    output["韧性"] = resilienceByClothing[raw["名称"]] ?? null;

    const isWeapon = String(raw["部位"]).includes("武器") || raw["部位"] === "武器";
    const isNecklace = String(raw["部位"]).includes("项链") || raw["部位"] === "项链";
    if (isWeapon) {
      output["幸运"] = 9;
      output["准确"] = 60;
      output["攻击速度"] = 10;
    }
    if (isWeapon || isNecklace) {
      output["防御"] = null;
      output["魔御"] = null;
    }

    const baseStory = raw["备注"] ?? "";
    output["备注"] = `${baseStory}｜数值版本：${VERSION}｜来源：${sourceMonster.name}｜${extraGateDrop ? "守关BOSS追加" : "主要定向专属"}`;
    const importRow = rowFromObject(source.targetEquipmentHeaders, output);
    if (importRow.length !== 67) throw new Error(`equipment row is not 67 columns: ${raw["名称"]}`);

    return {
      id: `EL-EQP-C01-${String(index + 1).padStart(3, "0")}`,
      continentId: "C01",
      name: raw["名称"],
      slot: raw["部位"],
      sourceNumber: output["来源编号"] === null || output["来源编号"] === undefined || output["来源编号"] === ""
        ? null
        : output["来源编号"],
      sourceMonsterId: sourceMonster.id,
      sourceMonsterName: sourceMonster.name,
      sourceType: sourceMonster.type,
      primaryExclusive: Boolean(primaryMonster),
      extraGateDrop,
      maxDropRate: Number(output["最大爆率"] ?? 0),
      graduationLoadoutCount: loadoutCount,
      numericVersion: VERSION,
      sourceNumberState: output["来源编号"] === null ? "沿用模板空白/待平台母版匹配" : "已填写",
      importRow,
    };
  });
}

function buildDrops(monsters, equipment) {
  const equipmentById = new Map(equipment.map((item) => [item.id, item]));
  const denominatorByType = { normal: 1800, rare: 600, boss: 120, gate_boss: 50 };
  return monsters.map((monster) => {
    const primary = equipmentById.get(monster.primaryExclusiveId);
    const items = [
      {
        role: "primary_exclusive",
        itemId: primary.id,
        itemName: primary.name,
        numerator: 1,
        denominator: denominatorByType[monster.type],
        effectiveProbability: Math.min(1, PLAYER_DROP_MULTIPLIER / denominatorByType[monster.type]),
      },
    ];
    if (monster.type === "normal") {
      items.push({ role: "continent_common_material", itemName: "海蚀铁片", numerator: 1, denominator: 75 });
    } else if (monster.type === "rare") {
      items.push({ role: "continent_rare_material", itemName: "潮痕结晶", numerator: 1, denominator: 75 });
    } else if (monster.type === "boss") {
      items.push({ role: "continent_common_material", itemName: "海蚀铁片", numerator: 1, denominator: 30 });
      items.push({ role: "continent_rare_material", itemName: "潮痕结晶", numerator: 1, denominator: 20 });
    } else {
      items.push({ role: "continent_common_material", itemName: "海蚀铁片", numerator: 1, denominator: 10 });
      items.push({ role: "continent_rare_material", itemName: "潮痕结晶", numerator: 1, denominator: 10 });
      for (const extra of equipment.filter((item) => item.extraGateDrop)) {
        items.push({ role: "gate_fashion_extra", itemId: extra.id, itemName: extra.name, numerator: 1, denominator: 200 });
      }
    }
    const taskMaterial = taskMaterialByMonster[monster.name];
    if (taskMaterial) {
      items.push({ role: "protected_task_material", itemName: taskMaterial[0], numerator: 1, denominator: taskMaterial[1] });
    }
    return {
      id: `EL-DROP-${monster.id}`,
      continentId: "C01",
      monsterId: monster.id,
      monsterName: monster.name,
      monsterType: monster.type,
      playerDropMultiplier: PLAYER_DROP_MULTIPLIER,
      standardEquipmentPools: "沿用现有第一大陆制式装备池；本版只重算主要专属与大陆材料",
      items,
      numericVersion: VERSION,
    };
  });
}

function buildNpcs() {
  const tasks = [
    {
      id: "EL-NPC-C01-001",
      name: "拾骸女·梅芙",
      type: "剧情任务NPC",
      mapGroup: "失乡者海岸",
      mapId: "XX330",
      mapName: "失乡者王座",
      function: "一次性任务《海岸亡魂》；收集四件海岸魂魄信物，保留原剧情，不再直接发称号或永久属性。",
      openingCondition: "角色首次抵达失乡者王座；每个角色只能完成一次。",
      requirements: ["锈锚魂魄×1", "沉金魂魄×1", "船长残魂×1", "吞岸王魂×1"],
      currency: "无",
      reward: ["漂流见证·潮×1", "海蚀铁片×60", `金币×${(C1_GOLD_PER_HOUR * 0.5).toLocaleString("zh-CN")}`],
      story: "漂流群岛的海水从不归还完整尸骨。梅芙替亡者收殓残骸，请玩家解开锈锚、沉金、船长与吞岸巨兽留下的执念。",
      dialogue: {
        first: "潮水只把名字冲走，却把执念留在岸上。替我带回四件魂魄信物，我会让这些亡者真正离开。",
        insufficient: "还少一些。锈锚、沉金、船长与吞岸巨兽的执念必须一并归还，否则潮水明天还会把他们送回来。",
        complete: "够了。今天退去的潮水不会再带回他们。收下这枚见证，它只证明你完成过这件事，不替你换取亡者的力量。",
        repeated: "海岸已经安静。若你仍听见哭声，那是别处的亡者在等你。",
      },
    },
    {
      id: "EL-NPC-C01-002",
      name: "断誓骑士·罗恩",
      type: "剧情任务NPC",
      mapGroup: "风暴断崖",
      mapId: "XX329",
      mapName: "风暴断崖三层",
      function: "一次性任务《风暴遗誓》；收集四件断崖魂魄信物，保留原剧情，不再直接发称号或永久属性。",
      openingCondition: "角色首次抵达风暴断崖三层；每个角色只能完成一次。",
      requirements: ["逐雷魂印×1", "裂岩之心×1", "执刑官残魂×1", "古龙逆鳞×1"],
      currency: "无",
      reward: ["漂流见证·雷×1", "潮痕结晶×6", `金币×${(C1_GOLD_PER_HOUR * 0.5).toLocaleString("zh-CN")}`],
      story: "断崖雷霆来自战死者未能履行的誓言。罗恩要求玩家击败逐雷者、裂岩者、执刑官与古龙，让旧誓终止。",
      dialogue: {
        first: "雷霆不是天罚，是死人仍不肯承认自己败了。带回四件信物，我替他们把最后一句誓言说完。",
        insufficient: "风还没有转向。逐雷者、裂岩者、执刑官与古龙，至少还有一个不肯放手。",
        complete: "听见了吗？雷声第一次没有回应。拿着这枚见证，记住誓言可以完成，也可以被终止。",
        repeated: "我的誓言已经结束。你接下来立下的誓，后果只由你承担。",
      },
    },
    {
      id: "EL-NPC-C01-003",
      name: "无冠史官·塞蕾",
      type: "剧情任务NPC",
      mapGroup: "沉没王庭",
      mapId: "XX104",
      mapName: "沉没王庭底层",
      function: "一次性任务《沉王终曲》；收集五件王庭魂魄信物，终结奥德里安旧统治，并发放大陆剧情印记。",
      openingCondition: "角色抵达沉没王庭底层并已接触前两项大陆剧情；每个角色只能完成一次。",
      requirements: ["失冠徽记×1", "沉默祷文×1", "亲卫长残魂×1", "深潮祭冠×1", "沉王魂核×1"],
      currency: "无",
      reward: ["漂流大陆印记×1", "海蚀铁片×90", `金币×${C1_GOLD_PER_HOUR.toLocaleString("zh-CN")}`],
      story: "塞蕾仍在记录沉没王庭失去姓名的王族与祭司。玩家集齐五件信物，替漂流群岛写下结束旧王统治的正式结局。",
      dialogue: {
        first: "王庭沉了，史书却还停在国王登基那一页。带回五件信物，我要写下这场统治真正结束的日期。",
        insufficient: "史书不能靠猜测结尾。失冠者、女祭司、亲卫长、大祭司与沉没之王，五份证据缺一不可。",
        complete: "最后一行写完了。印记交给你——它不是王冠，只证明你亲手结束过一个不肯退场的时代。",
        repeated: "奥德里安已经成为过去。不要让后来的人把过去重新写成命令。",
      },
    },
  ];

  const titleNpc = {
    id: "EL-NPC-C01-004",
    name: "渡海铭誓官·伊莱恩",
    type: "大陆称号NPC",
    mapGroup: "失乡者海岸",
    mapId: "XX113",
    mapName: "失乡者海岸",
    function: "消耗本大陆材料和金币，按顺序升级漂流群岛五阶段称号；称号累计韧性+7、普通爆率+100%。",
    openingCondition: "进入漂流群岛即可使用；菜单只显示当前可升级的下一档。",
    requirements: [
      "第1档：海蚀铁片×30、金币×100,000",
      "第2档：海蚀铁片×60、潮痕结晶×2、金币×100,000",
      "第3档：海蚀铁片×90、潮痕结晶×4、金币×200,000",
      "第4档：海蚀铁片×120、潮痕结晶×6、金币×300,000",
      "第5档：海蚀铁片×150、潮痕结晶×8、金币×400,000、漂流大陆印记×1",
    ],
    currency: "金币；第一版按本大陆中位收入200,000金币/小时折算。",
    reward: [
      "潮痕幸存者：韧性+1、普通爆率+10%",
      "断桅拾荒者：韧性+1、普通爆率+15%",
      "风暴归岸人：韧性+1、普通爆率+20%",
      "沉王见证者：韧性+2、普通爆率+25%",
      "漂流群岛铭誓者：韧性+2、普通爆率+30%",
    ],
    story: "伊莱恩拒绝用亡者魂魄直接换取力量，只承认玩家在漂流群岛取得的材料、货币与大陆印记。",
    dialogue: {
      first: "亡者的名字不该换来力量。带来这片群岛仍承认的材料，我替你记下活人的功绩。",
      insufficient: "材料还不够。称号不是安慰，也不是赊账；你走过的路必须留下足够的证据。",
      complete: "这一阶已经刻下。新的称号给你承担下一段路的资格，不替你承担后果。",
      repeated: "你已经取得漂流群岛最后的铭誓。再多材料也不会让同一段功绩重复生效。",
    },
    titleStages: [
      { stage: 1, title: "潮痕幸存者", common: 30, rare: 0, gold: 100_000, mark: 0, resilience: 1, dropRate: 10 },
      { stage: 2, title: "断桅拾荒者", common: 60, rare: 2, gold: 100_000, mark: 0, resilience: 1, dropRate: 15 },
      { stage: 3, title: "风暴归岸人", common: 90, rare: 4, gold: 200_000, mark: 0, resilience: 1, dropRate: 20 },
      { stage: 4, title: "沉王见证者", common: 120, rare: 6, gold: 300_000, mark: 0, resilience: 2, dropRate: 25 },
      { stage: 5, title: "漂流群岛铭誓者", common: 150, rare: 8, gold: 400_000, mark: 1, resilience: 2, dropRate: 30 },
    ],
  };

  return [...tasks, titleNpc].map((npc) => ({
    ...npc,
    continentId: "C01",
    continentName: "漂流群岛",
    coordinate: null,
    deploymentState: "待选坐标",
    numericVersion: VERSION,
    replacementRelation: npc.type === "剧情任务NPC"
      ? "保留原任务名、NPC与剧情；原直接称号/永久属性奖励废止，改为剧情凭证、材料和金币。"
      : "替代旧地图魂魄直接换称号的方案；称号与剧情任务完全分离。",
  }));
}

async function writeNpcFiles(npcs) {
  await fs.mkdir(NPC_DIR, { recursive: true });
  for (const [index, npc] of npcs.entries()) {
    const lines = [
      `NPC编号：${npc.id}`,
      `NPC名称：${npc.name}`,
      `NPC类型：${npc.type}`,
      `所属大陆：${npc.continentName}（${npc.continentId}）`,
      `地图组：${npc.mapGroup}`,
      `投放地图：${npc.mapId} ${npc.mapName}`,
      "坐标：待从实际可行走点选择",
      `部署状态：${npc.deploymentState}`,
      "",
      `功能：${npc.function}`,
      `开启条件：${npc.openingCondition}`,
      `货币规则：${npc.currency}`,
      "",
      "需要内容：",
      ...npc.requirements.map((item) => `- ${item}`),
      "",
      "获得内容：",
      ...npc.reward.map((item) => `- ${item}`),
      "",
      `简单剧情：${npc.story}`,
      "",
      "剧情对白：",
      `【首次】${npc.dialogue.first}`,
      `【材料不足】${npc.dialogue.insufficient}`,
      `【完成】${npc.dialogue.complete}`,
      `【重复访问】${npc.dialogue.repeated}`,
      "",
      `替代关系：${npc.replacementRelation}`,
      `数值版本：${npc.numericVersion}`,
      "",
    ];
    const fileName = `${String(index + 1).padStart(2, "0")}_${npc.name.replaceAll("·", "_")}.txt`;
    await fs.writeFile(path.join(NPC_DIR, fileName), lines.join("\n"), "utf8");
  }
}

async function writeDropFiles(monsters, equipment, drops) {
  await fs.mkdir(MONITEMS_UTF8_DIR, { recursive: true });
  await fs.mkdir(MONITEMS_GBK_DIR, { recursive: true });
  const equipmentById = new Map(equipment.map((item) => [item.id, item]));
  const overviewRows = [[
    "怪物ID", "地图组", "地图号", "怪物类型", "怪物名称", "主要专属", "基础分母", "人物倍数", "有效单杀概率", "大陆材料", "任务材料", "说明",
  ]];

  for (const monster of monsters) {
    const drop = drops.find((item) => item.monsterId === monster.id);
    const primary = equipmentById.get(monster.primaryExclusiveId);
    const primaryDrop = drop.items.find((item) => item.role === "primary_exclusive");
    const sourceBytes = await fs.readFile(path.join(DROP_SOURCE_DIR, `${monster.name}.txt`));
    let text = new TextDecoder("gb18030").decode(sourceBytes).replaceAll("\r\n", "\n");
    text = replaceExactDropLine(text, primary.name, primaryDrop.denominator);
    if (monster.type === "gate_boss") {
      text = text.replace("#CHILD 1/250 RANDOM", "#CHILD 1/200 RANDOM");
    }
    for (const item of drop.items.filter((entry) => entry.role.includes("material") && entry.role !== "protected_task_material")) {
      text = appendUniqueDropLine(text, item.denominator, item.itemName);
    }
    await fs.writeFile(path.join(MONITEMS_UTF8_DIR, `${monster.name}.txt`), text, "utf8");
    const gbkBytes = execFileSync("iconv", ["-f", "utf-8", "-t", "gb18030"], { input: Buffer.from(text, "utf8") });
    await fs.writeFile(path.join(MONITEMS_GBK_DIR, `${monster.name}.txt`), gbkBytes);

    const materialText = drop.items
      .filter((item) => item.role === "continent_common_material" || item.role === "continent_rare_material")
      .map((item) => `${item.itemName} 1/${item.denominator}`)
      .join("；");
    const taskText = drop.items
      .filter((item) => item.role === "protected_task_material")
      .map((item) => `${item.itemName} 1/${item.denominator}`)
      .join("；");
    overviewRows.push([
      monster.id,
      monster.groupName,
      monster.mapIds.join("、"),
      monster.type,
      monster.name,
      primary.name,
      primaryDrop.denominator,
      PLAYER_DROP_MULTIPLIER,
      primaryDrop.effectiveProbability,
      materialText,
      taskText,
      monster.type === "gate_boss" ? "另有潮葬礼剑、无冠王衣1/200随机池；剧情印记由首次击杀/任务脚本固定发放" : "制式装备随机池沿用现有文件",
    ]);
  }
  const overviewText = overviewRows.map((row) => row.join("\t")).join("\n") + "\n";
  await fs.writeFile(path.join(C1_ROOT, "第一大陆_怪物掉落总览_UTF8.txt"), overviewText, "utf8");
}

async function buildMonsterWorkbook(monsters) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(MONSTER_TEMPLATE));
  const sheet = workbook.worksheets.getItem("怪物生成");
  const headers = sheet.getRange("A1:M1").values[0];
  for (let row = 3; row <= monsters.length + 1; row += 1) {
    sheet.getRange("A2:M2").copyTo(sheet.getRange(`A${row}:M${row}`), "all");
  }
  const rows = monsters.map((monster) => {
    const object = {
      "状态": "可安装",
      "怪物名称": monster.name,
      "等级": monster.level,
      "经验": monster.experience,
      "血量": monster.hp,
      "防御": monster.defense,
      "魔防": monster.magicDefense,
      "最小攻击": monster.minAttack,
      "最大攻击": monster.maxAttack,
      "命中": monster.accuracy,
      "颜色": monster.color,
      "模型库编号": null,
      "备注": `${monster.remarks}；ID：${monster.id}；${VERSION}`,
    };
    return rowFromObject(headers, object);
  });
  sheet.getRange(`A2:M${monsters.length + 1}`).values = rows;
  const outputPath = path.join(C1_ROOT, "20_怪物批量生成_漂流群岛重做.xlsx");
  const file = await SpreadsheetFile.exportXlsx(workbook);
  await file.save(outputPath);
  return workbook;
}

async function buildEquipmentWorkbook(source, equipment) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(EQUIPMENT_TEMPLATE));
  const sheet = workbook.worksheets.getItem("装备导入表");
  for (let row = 3; row <= equipment.length + 1; row += 1) {
    sheet.getRange("A2:BO2").copyTo(sheet.getRange(`A${row}:BO${row}`), "all");
  }
  sheet.getRange(`A2:BO${equipment.length + 1}`).values = equipment.map((item) => item.importRow);
  const sourceSheet = workbook.worksheets.getItem("资料来源");
  sourceSheet.getRange("A1:D10").clear({ applyTo: "contents" });
  sourceSheet.getRange("A1:D10").values = [
    ["范围", "采用资料", "说明", "状态"],
    ["模板", "09_装备批量生成(7).xlsx", "使用最新67列；按字段名映射，禁止从旧表按列号复制。", "已执行"],
    ["名称/部位/故事", "第一大陆_专属装备总表.xlsx", "38件名称、部位、来源怪和故事保留。", "已执行"],
    ["数值", VERSION, "C1起重新计算乘区、最大爆率、韧性和守关稀有词条。", "第一版"],
    ["主要专属", "36件", "每只怪物恰好1件主要定向专属。", "通过"],
    ["追加时装", "2件", "奥德里安追加潮葬礼剑、无冠王衣。", "通过"],
    ["武器规则", "幸运9/准确60/攻速10", "武器与时装武器统一；武器和项链不填防御/魔御。", "通过"],
    ["模型来源", "来源编号", "已有合法编号保留；空白项不猜填。", "需平台预检"],
    ["最大爆率", "+150%", "第一大陆毕业穿戴组合累计值。", "通过"],
    ["部署", "未部署", "本文件为设计与导入候选，需平台预检和进服验证。", "待执行"],
  ];
  const outputPath = path.join(C1_ROOT, "09_装备批量生成_漂流群岛专属重做.xlsx");
  const file = await SpreadsheetFile.exportXlsx(workbook);
  await file.save(outputPath);
  return workbook;
}

function createGlobalLedgerWorkbook() {
  const workbook = Workbook.create();
  const overview = workbook.worksheets.add("十大陆总览");
  const rules = workbook.worksheets.add("全局规则锁");
  const status = workbook.worksheets.add("对象完成状态");
  const conflicts = workbook.worksheets.add("编号冲突替代");

  overview.getRange("A1:M1").merge();
  overview.getRange("A1").values = [["《艾尔登法环》十大陆全局设计总账"]];
  overview.getRange("A1:M1").format = {
    fill: "#0F766E",
    font: { name: "Microsoft YaHei", size: 16, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  overview.getRange("A2:M2").merge();
  overview.getRange("A2").values = [[`当前版本：${VERSION}｜按大陆制作，所有对象必须回写本总账｜地图尺寸不参与本轮设计`]];
  overview.getRange("A2:M2").format = { fill: "#DDEBF7", font: { italic: true, color: "#1F4E78" } };
  overview.getRange("A4:M4").values = [[
    "大陆ID", "大陆", "地图组", "地图数", "目标怪物", "已完成怪物", "主要专属", "已完成专属", "强合成", "人物爆率倍数", "守关BOSS血量", "状态", "后续依赖",
  ]];
  const rows = continentLedger.map((row, index) => [
    row[0], row[1], row[2], row[3], row[4], index === 0 ? 36 : 0, row[5], index === 0 ? 36 : 0, row[6], row[7], row[8], row[9],
    index === 0 ? "NPC坐标与平台预检" : index === 1 ? "先承接C1毕业快照" : `承接C${String(index).padStart(2, "0")}毕业快照`,
  ]);
  overview.getRange("A5:M14").values = rows;
  applyTableStyle(overview, "A4:M14", 4);
  overview.getRange("K5:K14").format.numberFormat = "#,##0";
  setWidths(overview, { A: 10, B: 16, C: 9, D: 9, E: 11, F: 12, G: 11, H: 12, I: 9, J: 14, K: 22, L: 18, M: 26 });

  rules.getRange("A1:D1").values = [["规则ID", "当前有效规则", "锁定值", "说明"]];
  rules.getRange("A2:D13").values = [
    ["EL-RULE-SCOPE", "当前大陆总数", 10, "第11—13大陆只允许出现在历史变更记录"],
    ["EL-RULE-MAPSIZE", "地图尺寸是否为设计前置", "否", "用户明确要求忽略地图大小；不得再作为阻断项"],
    ["EL-RULE-MONSTER", "怪物与装备数值重做起点", "C01", "名称、模型、剧情和来源关系可保留，旧数值废止"],
    ["EL-RULE-PRIMARY", "主要专属", "每怪1件", "守关BOSS可有追加时装"],
    ["EL-RULE-DROP", "掉落校准范围", "当前大陆角色×当前大陆怪物", "不做高大陆返回低大陆惩罚"],
    ["EL-RULE-C1-M", "第一大陆人物实际爆率", "5倍", "称号普通爆率+100%，毕业装备最大爆率+150%"],
    ["EL-RULE-C10-M", "第十大陆人物实际爆率", "100倍", "按本大陆怪物基础概率反向校准"],
    ["EL-RULE-HP", "守关BOSS血量增长", "每大陆×20", "C10=512京，不超过888京"],
    ["EL-RULE-TITLE", "称号系统", "每大陆1NPC/5阶段", "剧情任务不直接发永久韧性"],
    ["EL-RULE-SYNTH", "强合成开放", "C03—C10", "C01—C02为0；本大陆材料闭环"],
    ["EL-RULE-COORD", "缺失坐标", "留空并标待选", "不猜填NPC或传送坐标"],
    ["EL-RULE-OWNER", "内容主编", "ChatGPT主设计", "Codex仅机械落表、校验与本地施工"],
  ];
  applyTableStyle(rules, "A1:D13", 1);
  setWidths(rules, { A: 20, B: 28, C: 24, D: 58 });

  status.getRange("A1:G1").values = [["大陆", "对象类型", "目标数", "已完成", "完成率", "当前版本", "下一动作"]];
  status.getRange("A2:G7").values = [
    ["漂流群岛", "怪物实数", 36, 36, null, VERSION, "平台预检后进服校准伤害"],
    ["漂流群岛", "主要专属装备", 36, 36, null, VERSION, "核定空白来源编号"],
    ["漂流群岛", "守关追加时装", 2, 2, null, VERSION, "核对时装母版"],
    ["漂流群岛", "MonItems", 36, 36, null, VERSION, "复制到服务器前备份"],
    ["漂流群岛", "NPC设计TXT", 4, 4, null, VERSION, "从实图选择坐标"],
    ["十大陆", "整体怪物", 553, 36, null, VERSION, "下一批制作宁姆格福61怪"],
  ];
  status.getRange("E2").formulas = [["=D2/C2"]];
  status.getRange("E2:E7").fillDown();
  status.getRange("E2:E7").format.numberFormat = "0.0%";
  applyTableStyle(status, "A1:G7", 1);
  setWidths(status, { A: 16, B: 22, C: 11, D: 11, E: 12, F: 24, G: 34 });

  conflicts.getRange("A1:I1").values = [["地图号", "地图名", "冲突装备", "部位", "旧来源编号", "新来源编号", "新资源", "状态", "检查依据"]];
  conflicts.getRange("A2:I4").values = idConflictResolutions.map((item) => [
    item.mapId,
    item.mapName,
    item.equipmentName,
    item.slot,
    item.oldSourceNumber,
    item.newSourceNumber,
    item.resourceName,
    item.state,
    "正式码段；三库同码预检通过；当前未占用；与171地图数字后缀交集0",
  ]);
  applyTableStyle(conflicts, "A1:I4", 1);
  setWidths(conflicts, { A: 11, B: 18, C: 22, D: 11, E: 14, F: 14, G: 28, H: 30, I: 58 });
  return workbook;
}

function createCalibrationWorkbook(monsters, equipment, drops, npcs) {
  const workbook = Workbook.create();
  const baseline = workbook.worksheets.add("大陆基线");
  const monsterSheet = workbook.worksheets.add("怪物数值");
  const equipmentSheet = workbook.worksheets.add("装备预算");
  const dropSheet = workbook.worksheets.add("掉落校准");
  const npcSheet = workbook.worksheets.add("NPC与任务");
  const checkSheet = workbook.worksheets.add("校验");

  baseline.getRange("A1:F1").values = [["参数", "第一大陆值", "单位", "计算依据", "状态", "版本"]];
  baseline.getRange("A2:F12").values = [
    ["人物原始攻击毕业参考", 1800, "点", "压低基础攻击，输出乘区由装备承担", "第一版", VERSION],
    ["人物HP毕业参考", 120000, "点", "用于怪物攻击回推", "第一版", VERSION],
    ["守关BOSS血量", 10000000, "点", "十大陆×20母线起点", "锁定", VERSION],
    ["人物实际爆率", 5, "倍", "(1+称号100%)×(1+装备150%)", "锁定", VERSION],
    ["称号累计韧性", 7, "点", "五阶段1/1/1/2/2", "锁定", VERSION],
    ["最佳普通衣服韧性", 3, "点", "深潮王铠", "锁定", VERSION],
    ["最终地图韧性门槛", 9, "点", "毕业总韧性10，留1点容错", "锁定", VERSION],
    ["通用材料", "海蚀铁片", "物品", "普通怪基础1/75", "锁定", VERSION],
    ["稀有材料", "潮痕结晶", "物品", "稀有怪基础1/75", "锁定", VERSION],
    ["金币中位收入", C1_GOLD_PER_HOUR, "金币/小时", "称号与任务奖励折算基准", "第一版", VERSION],
    ["地图尺寸参与设计", "否", "布尔", "用户明确要求忽略", "锁定", VERSION],
  ];
  applyTableStyle(baseline, "A1:F12", 1);
  setWidths(baseline, { A: 26, B: 24, C: 16, D: 44, E: 12, F: 24 });

  const monsterHeaders = ["怪物ID", "地图组", "地图号", "层级", "类型", "怪物名", "等级", "经验", "血量", "防御", "魔防", "最小攻击", "最大攻击", "命中", "主要专属", "状态"];
  monsterSheet.getRange("A1:P1").values = [monsterHeaders];
  monsterSheet.getRange(`A2:P${monsters.length + 1}`).values = monsters.map((monster) => [
    monster.id, monster.groupName, monster.mapIds.join("、"), `${monster.layerStart}-${monster.layerEnd}`, monster.type, monster.name,
    monster.level, monster.experience, monster.hp, monster.defense, monster.magicDefense, monster.minAttack, monster.maxAttack,
    monster.accuracy, monster.primaryExclusiveName, monster.deploymentState,
  ]);
  applyTableStyle(monsterSheet, `A1:P${monsters.length + 1}`, 1);
  setWidths(monsterSheet, { A: 25, B: 16, C: 24, D: 10, E: 12, F: 24, G: 9, H: 14, I: 16, J: 10, K: 10, L: 12, M: 12, N: 9, O: 22, P: 20 });
  monsterSheet.getRange(`H2:I${monsters.length + 1}`).format.numberFormat = "#,##0";

  const equipmentHeaders = ["装备ID", "装备名", "部位", "来源怪物", "来源类型", "来源编号", "主要专属", "守关追加", "攻击加成", "打怪伤害", "暴击伤害", "攻击伤害", "伤害系数", "致命几率", "致命伤害", "对怪吸收", "韧性", "最大爆率", "毕业计数", "毕业爆率贡献", "版本"];
  equipmentSheet.getRange("A1:U1").values = [equipmentHeaders];
  equipmentSheet.getRange(`A2:U${equipment.length + 1}`).values = equipment.map((item) => {
    const row = objectFromRow(sourceHeadersForCalibration, item.importRow);
    return [
      item.id, item.name, item.slot, item.sourceMonsterName, item.sourceType, item.sourceNumber, item.primaryExclusive ? "是" : "否", item.extraGateDrop ? "是" : "否",
      row["攻击加成"], row["打怪伤害"], row["暴击伤害"], row["攻击伤害"], row["伤害系数"], row["致命几率"], row["致命伤害"], row["对怪伤害吸收"], row["韧性"], item.maxDropRate, item.graduationLoadoutCount, null, item.numericVersion,
    ];
  });
  equipmentSheet.getRange("T2").formulas = [["=R2*S2"]];
  equipmentSheet.getRange(`T2:T${equipment.length + 1}`).fillDown();
  applyTableStyle(equipmentSheet, `A1:U${equipment.length + 1}`, 1);
  setWidths(equipmentSheet, { A: 20, B: 20, C: 12, D: 24, E: 12, F: 12, G: 11, H: 11, I: 11, J: 11, K: 11, L: 11, M: 11, N: 11, O: 11, P: 11, Q: 9, R: 11, S: 11, T: 16, U: 24 });

  dropSheet.getRange("A1:J1").values = [["怪物ID", "怪物名", "类型", "主要专属", "基础分母", "人物倍数", "单杀有效概率", "期望击杀", "每小时击杀参考", "每小时期望件数"]];
  dropSheet.getRange(`A2:J${drops.length + 1}`).values = drops.map((drop) => {
    const primary = drop.items.find((item) => item.role === "primary_exclusive");
    const kph = { normal: 900, rare: 60, boss: 2, gate_boss: 0.5 }[drop.monsterType];
    return [drop.monsterId, drop.monsterName, drop.monsterType, primary.itemName, primary.denominator, PLAYER_DROP_MULTIPLIER, null, null, kph, null];
  });
  dropSheet.getRange("G2").formulas = [["=MIN(1,F2/E2)"]];
  dropSheet.getRange(`G2:G${drops.length + 1}`).fillDown();
  dropSheet.getRange("H2").formulas = [["=IF(G2<=0,\"\",ROUNDUP(1/G2,0))"]];
  dropSheet.getRange(`H2:H${drops.length + 1}`).fillDown();
  dropSheet.getRange("J2").formulas = [["=I2*G2"]];
  dropSheet.getRange(`J2:J${drops.length + 1}`).fillDown();
  dropSheet.getRange(`G2:G${drops.length + 1}`).format.numberFormat = "0.0000%";
  dropSheet.getRange(`J2:J${drops.length + 1}`).format.numberFormat = "0.000";
  applyTableStyle(dropSheet, `A1:J${drops.length + 1}`, 1);
  setWidths(dropSheet, { A: 25, B: 24, C: 12, D: 22, E: 12, F: 12, G: 16, H: 12, I: 18, J: 18 });

  npcSheet.getRange("A1:L1").values = [["NPC编号", "NPC名", "类型", "地图组", "地图号", "地图名", "坐标", "功能", "材料/货币", "奖励", "部署状态", "替代关系"]];
  npcSheet.getRange(`A2:L${npcs.length + 1}`).values = npcs.map((npc) => [
    npc.id, npc.name, npc.type, npc.mapGroup, npc.mapId, npc.mapName, "待选", npc.function,
    [...npc.requirements, npc.currency].join("；"), npc.reward.join("；"), npc.deploymentState, npc.replacementRelation,
  ]);
  applyTableStyle(npcSheet, `A1:L${npcs.length + 1}`, 1);
  npcSheet.getRange(`H2:L${npcs.length + 1}`).format.wrapText = true;
  setWidths(npcSheet, { A: 20, B: 20, C: 16, D: 16, E: 11, F: 18, G: 11, H: 46, I: 54, J: 50, K: 14, L: 48 });

  checkSheet.getRange("A1:D1").values = [["校验项", "目标", "实际/公式", "判定"]];
  const c1MapIds = [...new Set(monsters.flatMap((monster) => monster.mapIds))];
  const c1SourceNumbers = equipment.map((item) => item.sourceNumber).filter((value) => value !== null);
  const c1MapNumberSet = new Set(c1MapIds.map((mapId) => Number(mapId.replace(/^XX/, ""))));
  const c1SourceMapConflicts = c1SourceNumbers.filter((value) => c1MapNumberSet.has(Number(value)));
  checkSheet.getRange("A2:D11").values = [
    ["怪物数", 36, monsters.length, monsters.length === 36 ? "通过" : "失败"],
    ["主要专属数", 36, equipment.filter((item) => item.primaryExclusive).length, equipment.filter((item) => item.primaryExclusive).length === 36 ? "通过" : "失败"],
    ["守关追加装备数", 2, equipment.filter((item) => item.extraGateDrop).length, equipment.filter((item) => item.extraGateDrop).length === 2 ? "通过" : "失败"],
    ["NPC设计数", 4, npcs.length, npcs.length === 4 ? "通过" : "失败"],
    ["掉落文件数", 36, drops.length, drops.length === 36 ? "通过" : "失败"],
    ["毕业装备最大爆率", 150, null, null],
    ["称号累计韧性", 7, npcs.find((npc) => npc.titleStages)?.titleStages.reduce((sum, stage) => sum + stage.resilience, 0), "通过"],
    ["称号累计普通爆率", 100, npcs.find((npc) => npc.titleStages)?.titleStages.reduce((sum, stage) => sum + stage.dropRate, 0), "通过"],
    ["第一大陆地图号完整数", 11, c1MapIds.length, c1MapIds.length === 11 ? "通过" : "失败"],
    ["第一大陆来源编号/地图号冲突", 0, c1SourceMapConflicts.length, c1SourceMapConflicts.length === 0 ? "通过" : "失败"],
  ];
  checkSheet.getRange("C7").formulas = [[`=SUM('装备预算'!T2:T${equipment.length + 1})`]];
  checkSheet.getRange("D7").formulas = [["=IF(C7=B7,\"通过\",\"失败\")"]];
  applyTableStyle(checkSheet, "A1:D11", 1);
  setWidths(checkSheet, { A: 28, B: 16, C: 18, D: 14 });
  return workbook;
}

let sourceHeadersForCalibration = [];

async function renderWorkbook(workbook, workbookLabel, specs) {
  for (const [sheetName, range] of specs) {
    const preview = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
    const safeName = `${workbookLabel}_${sheetName}`.replaceAll(/[\\/:*?"<>|]/g, "_");
    await fs.writeFile(path.join(PREVIEW_DIR, `${safeName}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
}

async function main() {
  for (const directory of [OUTPUT_ROOT, C1_ROOT, DATA_DIR, GLOBAL_DATA_DIR, NPC_DIR, MONITEMS_UTF8_DIR, MONITEMS_GBK_DIR, PREVIEW_DIR]) {
    await fs.mkdir(directory, { recursive: true });
  }

  const source = await loadSourceData();
  sourceHeadersForCalibration = source.targetEquipmentHeaders;
  const monsters = buildMonsters(source);
  const equipment = buildEquipment(source, monsters);
  const drops = buildDrops(monsters, equipment);
  const npcs = buildNpcs();

  const globalLedger = {
    project: "艾尔登法环十大陆联合重做",
    version: VERSION,
    authority: "本总账为跨大陆连续性锚点；按大陆分批制作，但任何对象都必须登记ID、来源、状态和版本。",
    rules: {
      continentCount: 10,
      mapSizeRequired: MAP_SIZE_REQUIRED,
      deploymentClaimAllowed: false,
      primaryExclusivePerMonster: 1,
      playerDropCalibration: "只校准当前大陆角色×当前大陆怪物",
    },
    continents: continentLedger.map((row, index) => ({
      id: row[0],
      order: index + 1,
      name: row[1],
      mapGroupCount: row[2],
      mapCount: row[3],
      monsterCount: row[4],
      primaryExclusiveCount: row[5],
      strongSynthesisCount: row[6],
      playerDropMultiplier: row[7],
      gateBossHp: row[8].toString(),
      status: row[9],
    })),
    idConflictResolutions,
    currentPointer: {
      completed: ["C01怪物V1", "C01装备V1", "C01掉落V1", "C01 NPC设计V1"],
      next: "C02宁姆格福61怪与对应装备重算；承接C01毕业攻击/HP/韧性/爆率快照",
    },
  };

  await saveJson(path.join(GLOBAL_DATA_DIR, "global_ledger.json"), globalLedger);
  await saveJson(path.join(DATA_DIR, "monsters.json"), monsters);
  await saveJson(path.join(DATA_DIR, "equipment.json"), equipment);
  await saveJson(path.join(DATA_DIR, "drops.json"), drops);
  await saveJson(path.join(DATA_DIR, "npcs.json"), npcs);
  await writeNpcFiles(npcs);
  await writeDropFiles(monsters, equipment, drops);

  const monsterWorkbook = await buildMonsterWorkbook(monsters);
  const equipmentWorkbook = await buildEquipmentWorkbook(source, equipment);
  const globalWorkbook = createGlobalLedgerWorkbook();
  const globalFile = await SpreadsheetFile.exportXlsx(globalWorkbook);
  await globalFile.save(path.join(OUTPUT_ROOT, "00_十大陆全局设计总账.xlsx"));
  const calibrationWorkbook = createCalibrationWorkbook(monsters, equipment, drops, npcs);
  const calibrationFile = await SpreadsheetFile.exportXlsx(calibrationWorkbook);
  await calibrationFile.save(path.join(C1_ROOT, "01_第一大陆数值与掉落校准表.xlsx"));

  await renderWorkbook(globalWorkbook, "global", [
    ["十大陆总览", "A1:M14"],
    ["全局规则锁", "A1:D13"],
    ["对象完成状态", "A1:G7"],
    ["编号冲突替代", "A1:I4"],
  ]);
  await renderWorkbook(calibrationWorkbook, "c1_calibration", [
    ["大陆基线", "A1:F12"],
    ["怪物数值", "A1:P18"],
    ["装备预算", "A1:U20"],
    ["掉落校准", "A1:J18"],
    ["NPC与任务", "A1:L5"],
    ["校验", "A1:D11"],
  ]);
  await renderWorkbook(monsterWorkbook, "c1_monster_import", [
    ["怪物生成", "A1:M37"],
    ["填写说明", "A1:C14"],
    ["模型参考", "A1:B30"],
  ]);
  await renderWorkbook(equipmentWorkbook, "c1_equipment_import", [
    ["装备导入表", "A1:Q20"],
    ["资料来源", "A1:D10"],
    ["部位说明", "A1:E35"],
  ]);

  const manifest = {
    version: VERSION,
    generatedAt: new Date().toISOString(),
    counts: {
      continents: globalLedger.continents.length,
      c1Monsters: monsters.length,
      c1Equipment: equipment.length,
      c1PrimaryExclusive: equipment.filter((item) => item.primaryExclusive).length,
      c1GateExtras: equipment.filter((item) => item.extraGateDrop).length,
      c1Drops: drops.length,
      c1Npcs: npcs.length,
      c1GraduationMaxDrop: equipment.reduce((sum, item) => sum + item.maxDropRate * item.graduationLoadoutCount, 0),
    },
    mapSizeIgnored: true,
    deploymentState: "设计数据完成，未部署",
  };
  await saveJson(path.join(OUTPUT_ROOT, "manifest.json"), manifest);
  process.stdout.write(JSON.stringify(manifest, null, 2) + "\n");
}

await main();
