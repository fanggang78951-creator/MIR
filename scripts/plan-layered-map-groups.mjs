import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { inspectMapFile } from 'file:///D:/XuanYuanDevPlatform/玄渊界面施工台/dist-electron/main/maps/map-reader.js';
import { readNativeMapCell } from 'file:///D:/XuanYuanDevPlatform/玄渊界面施工台/dist-electron/main/maps/map-structure-analysis.js';

const groups = [
  { seriesId: 'MOON_RIVER', name: '月河水域', maps: [['XX395', '月河走廊'], ['XX392', '月河小径'], ['XX391', '月河渊']] },
  { seriesId: 'FIRE_DRAGON', name: '火龙秘境', maps: [['XX485', '火龙通道'], ['XX484', '火龙崎路'], ['XX483', '火龙走廊'], ['XX482', '火龙地带'], ['XX481', '火龙神殿']] },
  { seriesId: 'ANT_CAVE', name: '蚂蚁洞窟', maps: [['XX550', '蚂蚁洞一层'], ['XX549', '蚂蚁洞二层'], ['XX573', '蚂蚁洞三层'], ['XX541', '蚂蚁洞四层'], ['XX419', '蚂蚁巢穴']] },
  { seriesId: 'WEST_SAND', name: '西沙遗迹', maps: [['XX518', '西沙走廊'], ['XX517', '西沙享殿'], ['XX516', '西沙地宫']] },
  { seriesId: 'GHOST_SHIP', name: '幽灵船', maps: [['XX527', '幽灵船上层'], ['XX457', '幽灵船底层'], ['XX582', '幽灵船密舱']] }
];

const clientMapRoot = 'D:/11周年/Map';
const outputRoot = path.resolve('outputs/layered-map-plan-20260813');
const fourWay = [[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]];

function isClear(bytes, layout, x, y) {
  return fourWay.every(([dx, dy]) => {
    const cell = readNativeMapCell(bytes, layout, x + dx, y + dy);
    return cell.walkable && !cell.door;
  });
}

function distance(left, right) {
  return Math.max(Math.abs(left.x - right.x), Math.abs(left.y - right.y));
}

function choosePortals(candidates, role) {
  if (!candidates.length) throw new Error('没有合格连接候选');
  if (role !== 'middle') return { [role]: candidates[0] };
  let best = null;
  for (let leftIndex = 0; leftIndex < candidates.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < candidates.length; rightIndex++) {
      const left = candidates[leftIndex];
      const right = candidates[rightIndex];
      const separation = distance(left, right);
      const score = separation * 100 + left.score + right.score;
      if (!best || score > best.score) best = { up: left, down: right, separation, score };
    }
  }
  if (!best) throw new Error('中层地图没有两组互不冲突的连接候选');
  return { up: best.up, down: best.down, separation: best.separation };
}

const reportGroups = [];
for (const group of groups) {
  const maps = [];
  for (let index = 0; index < group.maps.length; index++) {
    const [mapId, displayName] = group.maps[index];
    const mapPath = path.join(clientMapRoot, `${mapId}.map`);
    const inspection = await inspectMapFile(mapPath);
    const bytes = await readFile(mapPath);
    const layout = { width: inspection.width, height: inspection.height, cellSize: inspection.cellSize };
    const candidates = inspection.structure?.connectionCandidates ?? [];
    const role = index === 0 ? 'down' : index === group.maps.length - 1 ? 'up' : 'middle';
    const portals = choosePortals(candidates, role);
    for (const candidate of Object.values(portals).filter((value) => value && typeof value === 'object')) {
      if (!('x' in candidate)) continue;
      if (!isClear(bytes, layout, candidate.x, candidate.y)) throw new Error(`${mapId} 触发点净空失败`);
      if (!isClear(bytes, layout, candidate.landingX, candidate.landingY)) throw new Error(`${mapId} 落点净空失败`);
    }
    maps.push({
      mapId,
      displayName,
      width: inspection.width,
      height: inspection.height,
      sizeClass: inspection.structure?.sizeClass ?? 'unknown',
      spawnScale: inspection.structure?.spawnScale ?? 'unknown',
      role,
      portals
    });
  }
  const links = [];
  for (let index = 0; index < maps.length - 1; index++) {
    const a = maps[index];
    const b = maps[index + 1];
    const aPortal = a.portals.down;
    const bPortal = b.portals.up;
    links.push({
      seriesId: group.seriesId,
      aMapId: a.mapId,
      aTriggerX: aPortal.x,
      aTriggerY: aPortal.y,
      aAnimation: '下一层',
      aLandingX: aPortal.landingX,
      aLandingY: aPortal.landingY,
      bMapId: b.mapId,
      bTriggerX: bPortal.x,
      bTriggerY: bPortal.y,
      bAnimation: '上一层',
      bLandingX: bPortal.landingX,
      bLandingY: bPortal.landingY
    });
  }
  reportGroups.push({ seriesId: group.seriesId, name: group.name, maps, links });
}

const report = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  sourceRule: 'trigger-and-landing-four-way-one-cell',
  groups: reportGroups
};

const markdown = [
  '# XX383 后五组多层地图规划',
  '',
  `生成时间：${report.generatedAt}`,
  '',
  '门禁：触发点与落点自身及上下左右一格均可行走且非门单元。',
  '',
  ...reportGroups.flatMap((group) => [
    `## ${group.name}（${group.seriesId}）`,
    '',
    '| 层级 | 地图号 | 尺寸 | 档位 | 角色 | 上层入口 | 下层入口 |',
    '|---:|---|---|---|---|---|---|',
    ...group.maps.map((map, index) => {
      const up = map.portals.up ? `${map.portals.up.x},${map.portals.up.y} / 落点 ${map.portals.up.landingX},${map.portals.up.landingY}` : '-';
      const down = map.portals.down ? `${map.portals.down.x},${map.portals.down.y} / 落点 ${map.portals.down.landingX},${map.portals.down.landingY}` : '-';
      return `| ${index + 1} | ${map.mapId} | ${map.width}x${map.height} | ${map.sizeClass} | ${map.role} | ${up} | ${down} |`;
    }),
    ''
  ])
].join('\n');

await mkdir(outputRoot, { recursive: true });
await Promise.all([
  writeFile(path.join(outputRoot, 'layered-map-plan.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8'),
  writeFile(path.join(outputRoot, 'layered-map-plan.md'), `${markdown}\n`, 'utf8')
]);

console.log(JSON.stringify({ outputRoot, groups: reportGroups.map((group) => ({ seriesId: group.seriesId, maps: group.maps.map((map) => `${map.mapId}:${map.width}x${map.height}`), links: group.links.length })) }, null, 2));
