# 《艾尔登法环》第一大陆实际数据 V1

版本：`EL-C01-V1-20260820`

这是第一大陆“漂流群岛”的实际设计数据，不是空规划，也不代表已经部署。地图大小已从设计与门禁中排除。

## Codex读取顺序

1. `00_Codex执行与接续说明.md`
2. `global_ledger.json`
3. `C01_漂流群岛/data/monsters.json`
4. `C01_漂流群岛/data/equipment.json`
5. `C01_漂流群岛/data/drops.json`
6. `C01_漂流群岛/data/npcs.json`
7. 四份XLSX施工与校准表

本目录直接提供可阅读的规范化JSON、NPC文本和四份XLSX。36份UTF-8/GB18030 MonItems及全部预览、检查文件放在完整压缩包中。

## 还原完整压缩包

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\reassemble-package.ps1
```

生成：`艾尔登法环_第一大陆实际数据_V1_20260820.zip`

正确SHA-256：

```text
f43d31ecd745baae91f7c7693bdf7f146a18764d32c8f3dbba68a2ac4a0081b8
```

还原后再解压即可得到36份GB18030服务器掉落文件。

## 当前事实

- 36只怪物：17普通、12稀有、6地图BOSS、1守关BOSS。
- 38件装备：36件主要专属、2件守关BOSS追加时装。
- 36份掉落配置、4名NPC完整功能与对白。
- 第一大陆11个地图号齐全，第一大陆专属来源编号与地图号冲突为0。
- 全局旧冲突替代：战靴`821→6407`、项链`823→6401`、戒指`824→6403`，待回写旧制式装备表。
- 未提供的传送坐标与NPC坐标继续留空；不得伪造为已部署。

## 验证

```text
node --test tools/game-design/c1-actual-data.test.mjs
```

当前结果：7项测试全部通过；4份XLSX结构正常；36份GB18030文件与UTF-8原文往返一致。
