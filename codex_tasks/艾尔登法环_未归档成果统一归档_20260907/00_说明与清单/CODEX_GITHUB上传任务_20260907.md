# Codex任务：把2026-09-07统一包安全同步到GitHub

## 目标仓库与分支
- Repo: `fanggang78951-creator/MIR`
- Branch: `codex/elden-c1-c2-20260821`
- 打包时远端HEAD：`60c270835a1d13a6df70c96da807b4339f21591e`
- **禁止直接改 master，禁止 force push，禁止 reset --hard 到旧提交。**

## 0. 上传前先校验远端
```powershell
git fetch origin
git checkout codex/elden-c1-c2-20260821
git pull --ff-only origin codex/elden-c1-c2-20260821
git rev-parse HEAD
```
如果HEAD仍为 `60c270835a1d13a6df70c96da807b4339f21591e`，继续。
如果HEAD已经前进：**不要回退、不要强推**；先保留远端新增提交，在最新HEAD上应用本包，然后检查冲突。只有明确发现远端文件是本包旧版时才用本包最新版覆盖。

## 1. 解压与复制
压缩包内有 `UPLOAD_ROOT/`。把 `UPLOAD_ROOT/` 下的内容按相对路径复制到仓库根目录：
- 新建：`codex_tasks/艾尔登法环_未归档成果统一归档_20260907/`
- 覆盖：仓库根目录 `艾尔登法环_当前任务入口.md`

**不要把整个ZIP直接提交到repo根目录作为唯一成果。要提交解压后的实际文件。**

## 2. 覆盖规则
### 必须覆盖
- 仅覆盖根部 `艾尔登法环_当前任务入口.md`，让它指向20260907统一归档。

### 新建，不覆盖旧历史目录
- `codex_tasks/艾尔登法环_未归档成果统一归档_20260907/**`
- 不删除 `20260903`、`20260905` 等既有归档。

### 新旧版本冲突时的优先级
- 十大陆经济：V1.3 > V1.2 > V1.1 > V1.0
- NPC奖励/永久成长：V1.3 > V1.2 > V1.1 > V1.0
- 洗练/标准角色/爆率：V1.2 > V1.1 > V1.0
- 回收配置：V1.2 > V1.1 > V1.0
- C3-C10 464专属：V2.1来源编号修正版 > V2.0 > V1.0
- 新增56时装/时装生肖：V1.1已分配编号 > V1.0
- 38件合成：V2.1已分配编号 > V2.0 > V1.0
- 第一大陆118件：V4 > V3
- 40组人物：V1.1只保留为“装备重规划前模型”，**不能标记为当前最终人物数值**。

## 3. 严禁操作
- 不要把 `05_历史追溯_禁止覆盖新版/` 中任何旧表复制回当前目录。
- 不要把旧464件V1.0覆盖V2.1。
- 不要把旧38件V1.0/V2.0覆盖V2.1。
- 不要恢复7096—7217旧占位来源编号；当前V2.1已经按真实资源池/跨大陆复用规则修正。
- 不要更改用户本机已修改的6件追梦神器和16种称号卷数据。
- 不要修改游戏数据库、M2、客户端或正式脚本；本任务仅做Git归档。

## 4. 提交前校验
```powershell
git status --short
git diff --stat
git diff --name-status
```
确认：
1. 新目录存在；
2. 根部当前任务入口已更新；
3. 没有删除旧归档；
4. 没有意外修改游戏脚本/数据库/客户端文件；
5. 二进制XLSX都已实际加入Git，而不是只留下说明文字。

可再运行：
```powershell
git ls-files "codex_tasks/艾尔登法环_未归档成果统一归档_20260907/*"
```
并将输出与包内 `MANIFEST.json` 对照。

## 5. Commit与Push
建议单独一个提交：
```powershell
git add -- "艾尔登法环_当前任务入口.md" "codex_tasks/艾尔登法环_未归档成果统一归档_20260907"
git commit -m "design: archive Sep 7 economy character and equipment revisions"
git push origin codex/elden-c1-c2-20260821
```
不要合并到master。

## 6. 上传后回执
请输出：
- 最终分支HEAD SHA
- commit message
- `git status --short`（应为空）
- 新归档目录文件数
- 5个关键文件的Git blob/文件大小：经济V1.3、NPC V1.3、464 V2.1、56 V1.1、38 V2.1
- 确认根部 `艾尔登法环_当前任务入口.md` 已指向20260907目录

如果任何一步冲突或远端HEAD已前进，不得通过force解决；先报告差异。
