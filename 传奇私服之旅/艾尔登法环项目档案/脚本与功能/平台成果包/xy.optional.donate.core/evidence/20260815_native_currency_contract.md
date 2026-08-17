# 原生货币合同静态证据

- 平台货币栏只允许金币、元宝、灵符、金刚石及其原生/账户别名。
- 金币使用 `CHECKGOLD/GOLDCOUNT`。
- 元宝使用 `CHECKGAMEGOLD/GAMEGOLD`。
- 灵符使用 `CHECKGAMEGIRD/GAMEGIRD`。
- 金刚石使用 `CHECKGAMEDIAMOND/GAMEDIAMOND`。
- 普通背包物品只能作为材料；货币栏中的未知名称在预检阶段阻止。
- 2026-08-15 专项回归16项通过；当前服23/24号成长表生成结果中不存在 `CHECKITEM 元宝` 或 `TAKE 元宝`。

状态：静态验证通过，新增金币/元宝/金刚石捐献分支仍保持 candidate，待游戏内逐项验收。
