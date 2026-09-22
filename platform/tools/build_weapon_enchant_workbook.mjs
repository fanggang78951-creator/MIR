import { SpreadsheetFile, Workbook } from "file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const output = process.argv[2];
if (!output) throw new Error("usage: build_weapon_enchant_workbook.mjs <output.xlsx>");

const wb = Workbook.create();
const header = {
  fill: "#17365D",
  font: { name: "Microsoft YaHei", bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "middle",
  wrapText: true,
};
const body = {
  font: { name: "Microsoft YaHei", color: "#1F2937" },
  verticalAlignment: "middle",
  wrapText: true,
};

function finish(sheet, address, widths) {
  const [, end] = address.split(":");
  const lastColumn = end.replace(/\d+/g, "");
  const lastRow = end.replace(/\D+/g, "");
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(address).format = body;
  sheet.getRange(`A1:${lastColumn}1`).format = header;
  for (const [column, width] of widths) {
    sheet.getRange(`${column}1:${column}${lastRow}`).format.columnWidth = width;
  }
}

let sheet = wb.worksheets.add("基础设置");
const settings = [
  ["配置项", "配置值"],
  ["配置版本", 2],
  ["系统编号", "weapon_enchant"],
  ["目标装备部位", "武器"],
  ["允许StdMode", "5,6"],
  ["受管身份行", 9],
  ["兼容清理行", "9-11"],
  ["NPC脚本相对路径", "Mir200/Envir/Market_Def/玄渊武器附魔/武器附魔-3.txt"],
  ["NPC地图", "3"],
  ["NPC坐标X", 325],
  ["NPC坐标Y", 339],
  ["NPC名称", "武器附魔"],
  ["NPC外观", 220],
  ["物品框编号", 27],
  ["消耗类型", "元宝"],
  ["消耗名称", ""],
  ["消耗数量", 100],
  ["显示前缀", "附魔属性："],
  ["复用母版包ID", "xy.optional.equipment-wash-opening"],
];
sheet.getRange(`A1:B${settings.length}`).values = settings;
finish(sheet, `A1:B${settings.length}`, [["A", 22], ["B", 72]]);
sheet.getRange(`A2:A${settings.length}`).format.fill = "#EAF2F8";

sheet = wb.worksheets.add("结果候选");
const results = [
  ["词条编码", "显示名称", "属性来源", "属性名称", "适用技能", "效果类型", "效果值", "概率权重", "实际概率", "颜色", "是否启用"],
  ["LEGACY_POOL", "现有装备洗练池", "现有洗练池", "", "", "", 0, 94, 0, 151, "是"],
  ["SKILL_KT_CRIT", "开天斩必定暴击", "技能伤害", "必定暴击", "开天斩", "必定暴击", 100, 1, 0, 249, "是"],
  ["SKILL_KT_FATAL", "开天斩致命一击", "技能伤害", "致命一击", "开天斩", "致命一击", 200, 1, 0, 253, "是"],
  ["SKILL_ZR_CRIT", "逐日剑法必定暴击", "技能伤害", "必定暴击", "逐日剑法", "必定暴击", 100, 1, 0, 249, "是"],
  ["SKILL_ZR_FATAL", "逐日剑法致命一击", "技能伤害", "致命一击", "逐日剑法", "致命一击", 200, 1, 0, 253, "是"],
  ["SKILL_LH_CRIT", "烈火剑法必定暴击", "技能伤害", "必定暴击", "烈火剑法", "必定暴击", 100, 1, 0, 249, "是"],
  ["SKILL_LH_FATAL", "烈火剑法致命一击", "技能伤害", "致命一击", "烈火剑法", "致命一击", 200, 1, 0, 253, "是"],
  ["NATIVE_BLAST_9", "暴击伤害+9%", "已有洗练词条", "暴击伤害", "", "固定值", 9, 1, 0, 249, "否"],
  ["NATIVE_FATAL_3", "致命一击+3%", "已有洗练词条", "致命一击", "", "固定值", 3, 1, 0, 253, "否"],
  ["CANDIDATE_EXECUTE_3", "处决概率+3%", "预留属性", "处决概率", "", "固定值", 3, 1, 0, 70, "否"],
  ["CANDIDATE_LEVEL_1", "人物等级+1", "预留属性", "人物等级加成", "", "固定值", 1, 1, 0, 250, "否"],
  ["CANDIDATE_LEVEL_CAP_1", "人物等级上限+1", "预留属性", "人物等级上限加成", "", "固定值", 1, 1, 0, 250, "否"],
];
sheet.getRange(`A1:K${results.length}`).values = results;
sheet.getRange("I2").formulas = [['=IF(K2="是",IFERROR(H2/SUMIF($K$2:$K$1000,"是",$H$2:$H$1000),0),0)']];
sheet.getRange(`I2:I${results.length}`).fillDown();
sheet.getRange(`I2:I${results.length}`).format.numberFormat = "0.00%";
sheet.getRange("K2:K1000").dataValidation = { list: { source: ["是", "否"], inCellDropDown: true }, allowBlank: false };
finish(sheet, `A1:K${results.length}`, [["A", 24], ["B", 27], ["C", 18], ["D", 18], ["E", 16], ["F", 16], ["G", 12], ["H", 12], ["I", 13], ["J", 10], ["K", 11]]);
sheet.getRange("A2:K8").format.fill = "#EDF7ED";
sheet.getRange(`A9:K${results.length}`).format.fill = "#FFF4E5";

sheet = wb.worksheets.add("普通洗练设置");
const legacy = [
  ["结果名称", "是否启用", "触发分母", "颜色", "说明"],
  ["神佑", "是", 350, 125, "沿用已验收母版"],
  ["天赐", "是", 300, 31, "沿用已验收母版"],
  ["圣级", "是", 250, 70, "沿用已验收母版"],
  ["仙级", "是", 150, 253, "沿用已验收母版"],
  ["传说", "是", 10, 70, "沿用已验收母版"],
  ["上古", "是", 5, 253, "沿用已验收母版"],
  ["灵级", "是", 3, 215, "沿用已验收母版"],
];
sheet.getRange(`A1:E${legacy.length}`).values = legacy;
sheet.getRange("B2:B8").dataValidation = { list: { source: ["是", "否"], inCellDropDown: true }, allowBlank: false };
finish(sheet, `A1:E${legacy.length}`, [["A", 16], ["B", 13], ["C", 14], ["D", 10], ["E", 42]]);

sheet = wb.worksheets.add("词条路由库");
const nativeNames = [
  ["防御", "点"], ["魔御", "点"], ["攻击", "点"], ["魔法", "点"], ["道术", "点"], ["生命值", "点"], ["魔法值", "点"],
  ["暴击伤害", "%"], ["致命一击", "%"], ["攻击伤害", "%"], ["神圣一击", "点"], ["真实一击", "点"],
  ["麻痹一击", "点"], ["冰冻一击", "点"], ["攻击速度", "点"],
];
const routes = [
  ["属性来源", "属性名称", "路由", "状态", "单位", "适用范围", "说明"],
  ["现有洗练池", "", "legacy_pool", "verified", "", "武器", "调用已验证装备洗练结果池"],
  ["技能伤害", "必定暴击", "skill_damage_runtime", "verified", "%", "武器", "当前服已验证技能伤害运行时出口"],
  ["技能伤害", "致命一击", "skill_damage_runtime", "verified", "%", "武器", "当前服已验证技能伤害运行时出口"],
  ...nativeNames.map(([name, unit]) => ["已有洗练词条", name, "native_bind", "verified", unit, "武器", "沿用已验证洗练绑定"]),
  ["预留属性", "处决概率", "candidate", "candidate", "%", "武器", "未接入武器实例实效前启用会阻止"],
  ["预留属性", "人物等级加成", "candidate", "candidate", "级", "武器", "等待等级词条验证"],
  ["预留属性", "人物等级上限加成", "candidate", "candidate", "级", "武器", "等待等级上限词条验证"],
];
sheet.getRange(`A1:G${routes.length}`).values = routes;
finish(sheet, `A1:G${routes.length}`, [["A", 18], ["B", 21], ["C", 25], ["D", 14], ["E", 10], ["F", 13], ["G", 47]]);
sheet.getRange("A2:G19").format.fill = "#EDF7ED";
sheet.getRange(`A20:G${routes.length}`).format.fill = "#FFF4E5";

sheet = wb.worksheets.add("填写说明");
const help = [
  ["项目", "说明", "结果"],
  ["使用前提", "先安装并验收xy.optional.equipment-wash-opening；本包只派生，不修改底座。", "缺少或哈希漂移会阻止"],
  ["新增结果", "在结果候选末尾增加一行，词条编码必须唯一且部署后保持不变。", "支持N行"],
  ["概率", "实际概率=启用行权重÷全部启用行权重之和。", "自动计算"],
  ["默认概率", "现有洗练池94%；6条技能稀有结果各1%。", "可编辑"],
  ["普通词条", "复制已有洗练词条禁用示例并改为“是”。", "按原生绑定生效"],
  ["技能词条", "开天、逐日、烈火各有必定暴击和致命一击。", "当前端已验证，跨服需验收"],
  ["等级预留", "人物等级+X、等级上限+X暂只预留，启用会阻止。", "不伪造效果"],
  ["收费", "消耗数量即每次点击洗练费用，默认100元宝。", "可编辑"],
  ["回滚边界", "文件回滚不会自动恢复玩家已洗练的武器实例。", "实例需另行恢复"],
];
sheet.getRange(`A1:C${help.length}`).values = help;
finish(sheet, `A1:C${help.length}`, [["A", 18], ["B", 75], ["C", 27]]);
sheet.getRange(`A2:A${help.length}`).format.fill = "#EAF2F8";

const blob = await SpreadsheetFile.exportXlsx(wb);
await blob.save(output);
console.log(JSON.stringify({ output, schemaVersion: 2, sheets: wb.worksheets.items.map((item) => item.name), enabledResults: 7 }));
