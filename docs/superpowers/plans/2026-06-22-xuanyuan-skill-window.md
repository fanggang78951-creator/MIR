# 玄渊技能窗口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `DStateWin` 增加完整不透明的黑金底板，并让左侧“一至六”与六条技能逐行对齐，同时保持所有技能功能不变。

**Architecture:** 新底板作为独立的 `232 x 362`、24 位 BMP 资源加入 `D:\素材文件夹\全新聆风\LFM2[20260530]\登录器\NewopUI.Pak` 的空闲序号；同目录 `NewUI\Mir.ui` 只修改 `DStateWin` 背景绑定和六个序号控件的 Y 坐标。客户端目录仅在最终测试前同步，不使用 `D:\MirServer\登录器` 中的历史文件。

**Tech Stack:** MakeGameLogin 主界面编辑器、Wzl 资源编辑器、NewopUI.Pak、Mir.ui、24 位 BMP、Computer Use、PowerShell 文件校验。

---

### Task 1: 锁定生效文件并备份

**Files:**
- Backup: `D:\素材文件夹\全新聆风\LFM2[20260530]\登录器\NewUI\Mir.ui`
- Backup: `D:\素材文件夹\全新聆风\LFM2[20260530]\登录器\NewopUI.Pak`
- Inspect: `D:\11周年\Resources\Data\NewopUI.Pak`

- [ ] **Step 1: 记录三套文件的长度、修改时间和 SHA256**

Run: 对上述文件执行只读校验。

Expected: 明确当前编辑器和登录器均使用素材源目录；客户端 PAK 若被占用，则先记录占用状态，不强行覆盖。

- [ ] **Step 2: 创建带时间戳备份**

Run: 在原目录旁创建 `Backups\XY-SKILL-001-<timestamp>`，复制实际生效的 `Mir.ui` 与 `NewopUI.Pak`。

Expected: 备份文件长度与源文件一致，原文件不变。

### Task 2: 制作并验证黑金技能底板

**Files:**
- Create: `D:\MirServer\AI_Handoff\UI\中转文件夹\XY_SkillWindow_BlackGold_232x362_preview.png`
- Create: `D:\MirServer\AI_Handoff\UI\中转文件夹\XY_SkillWindow_BlackGold_232x362_24bit.bmp`

- [ ] **Step 1: 生成黑金完整框体预览**

Requirements: `232 x 362`；完整不透明黑底；暗铜金属外框；顶部标题区；中部留给六条原生技能控件；底部留分页区；不烘焙技能名称、经验、等级、升级字样或点击按钮。

- [ ] **Step 2: 验证资产格式**

Expected: PNG 与 BMP 均为 `232 x 362`；BMP 为 RGB 24 位；边角无透明像素；内容区不遮挡六条技能。

- [ ] **Step 3: 用户视觉确认**

Expected: 用户确认黑金外观后才进入 PAK 导入。

### Task 3: 导入空闲 PAK 序号

**Files:**
- Modify: `D:\素材文件夹\全新聆风\LFM2[20260530]\登录器\NewopUI.Pak`

- [ ] **Step 1: 在 Wzl 编辑器确认当前最大图片序号**

Expected: 确认 `01906` 是否空闲；不猜测序号。

- [ ] **Step 2: 停在尾部添加确认前请求用户确认**

Expected: 明确目标 PAK、目标序号和输入 BMP；不优化 PAK、不导入 PNG。

- [ ] **Step 3: 添加 24 位 BMP 并复查预览**

Expected: 新序号预览为完整黑金技能底板，尺寸正确，原 `01905` 背包资源不变。

### Task 4: 修改 DStateWin 与六项对齐

**Files:**
- Modify: 当前编辑器使用的 `NewUI\Mir.ui`

- [ ] **Step 1: 选择 `DStateWin` 主控件**

Expected: 属性显示宽 `232`、高 `362`；不误选 `DStMagBtn1-6`、背包或首饰盒。

- [ ] **Step 2: 修改背景资源绑定**

Expected: `DStateWin` 绑定实际加入 `NewopUI.Pak` 的图库映射和图片序号；背景不透明。

- [ ] **Step 3: 对齐左侧六个序号控件**

Expected: 六项共同起点 Y `48`、单行高度 `43`、间距 `5`，并与对应技能行中心对齐；X 坐标与控件功能保持原值。

- [ ] **Step 4: 保存界面文件**

Expected: 仅 `DStateWin` 背景绑定和六项 Y 坐标发生变化；文件长度和修改时间已记录。

### Task 5: 重新生成并测试

**Files:**
- Sync: `D:\11周年\Resources\Data\NewopUI.Pak`

- [ ] **Step 1: 完全关闭旧客户端**

Expected: 客户端不再占用 `NewopUI.Pak`。

- [ ] **Step 2: 同步 PAK 并重新生成登录器**

Expected: 源 PAK 与客户端 PAK 长度和 SHA256 一致；登录器生成成功。

- [ ] **Step 3: 进入游戏检查技能窗口**

Expected: 黑金底板完整可见且不透明；六条技能与“一至六”逐行对齐；技能图标、名称、经验、等级、升级和翻页功能正常。

- [ ] **Step 4: 输出施工总结**

Create: `D:\MirServer\AI_Handoff\UI\中转文件夹\XY-UI-SKILL-001_给ChatGPT看的总结.md`

Expected: 记录资产路径、PAK 序号、DStateWin 绑定、坐标变化、备份路径、同步哈希、测试结果和任何阻塞点。
