import { writeFile } from 'node:fs/promises';
import { inspectLayeredMapWorkbook } from 'file:///D:/XuanYuanDevPlatform/玄渊界面施工台/dist-electron/main/maps/layered-map-workbook-service.js';

const workbookPath = 'D:/XuanYuanDevPlatform/所需材料表格汇总/08_地图外显与多层传送_XX383后5组规划.xlsx';
const outputPath = 'C:/Users/Administrator/Documents/做传奇/outputs/layered-map-plan-20260813/platform-preflight.json';
const result = await inspectLayeredMapWorkbook({
  workbookPath,
  targetServerRoot: 'D:/MirServer',
  targetClientRoot: 'D:/11周年',
  platformRoot: 'D:/XuanYuanDevPlatform'
});
await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
console.log(JSON.stringify({
  state: result.state,
  blockers: result.blockers,
  warnings: result.warnings,
  displayNameCount: result.displayNameCount,
  bidirectionalLinkCount: result.bidirectionalLinkCount,
  transitionCount: result.transitions?.length ?? 0,
  modifiedFiles: result.modifiedFiles
}, null, 2));
if (result.blockers?.length) process.exitCode = 1;
