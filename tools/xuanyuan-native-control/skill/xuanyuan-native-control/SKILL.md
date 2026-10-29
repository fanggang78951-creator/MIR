---
name: xuanyuan-native-control
description: 在本机 Windows 中操作翎风/LFM2 游戏客户端、M2、GameCenter、LoginSrv、DBServer、RunGate、SelGate、微端服务器 UpdateServer_x64、微端网关 MirUpdateGate、登录器生成器及原版 WZL/PAK 编辑器。用于游戏输入、原生窗口与控件识别、字段设值、下拉与页签选择、保存按钮、菜单重读和自绘区域操作，以及登录器副本生成和资源导入导出；统一调用已发布工具并回读结果。
---

# 玄渊统一原生控制

把用户的具体任务路由到现有工具。首次使用先读取实际项目 AGENTS、`E:\XuanYuanDevPlatform\AGENTS.md` 和对应接口；用户已在当前任务明确授权的动作可直接推进。技能本身不授予生产端写入、启停引擎或发布权限，不要求为已授权范围内的每次点击重复询问。

## 唯一调用入口

先查询能力，之后所有请求都通过本技能的薄路由器执行：

```powershell
python -X utf8 'C:\Users\Administrator\.agents\skills\xuanyuan-native-control\scripts\invoke.py' --capabilities
python -X utf8 'C:\Users\Administrator\.agents\skills\xuanyuan-native-control\scripts\invoke.py' --adapter game --request 'D:\任务目录\request.json'
```

`--request -` 也接受 UTF-8 标准输入。请求沿用后端原 JSON 合同，不调用散落候选、不在任务中重写窗口控制脚本。路由器每次核对固定 EXE 与同目录 manifest 的指纹，以会话级互斥串行所有适配器；繁忙时报告冲突，重新观察后才能另发动作。

调用预算需覆盖后端完整流程。路由器正常存活时会一直持锁等待后端退出；如果外层被强制终止，锁可能释放而后端仍在运行。此时先只读核对后台工具/自有原版实例及当前画面，确认本轮后端已退出后再调用，不靠再次提交请求排查。

| adapter | 用户目标 | 后端与说明 |
|---|---|---|
| `game` | 悬浮、背包、跑动、攻击、单键操作 | Native Control；读 [game.md](references/game.md) |
| `m2` | M2 窗口、怪物字段编辑、保存、菜单重读、固定 Delphi 事件证据及原有命令 | Native Control；读 [native.md](references/native.md)、[window.md](references/window.md)；只读事件证据读 [event-evidence.md](references/event-evidence.md) |
| `engine` | GameCenter、固定版本 LoginSrv/DBServer/RunGate/SelGate、UpdateServer_x64 微端服务器与 MirUpdateGate 微端网关的窗口控件和菜单及原有隔离控制 | Native Control；读 [window.md](references/window.md)；启停另读 [native.md](references/native.md) |
| `launcher` | 生成器窗口控件、菜单，保存和生成登录器副本 | Native Control；窗口操作读 [window.md](references/window.md)，副本命令读 [native.md](references/native.md) |
| `editor` | 原版 WZL/PAK 编辑器的窗口、控件与自绘区域 | Native Control；读 [window.md](references/window.md)；资源批量处理用下一行 |
| `resource` | WZL/WZX、PAK 图片导入导出 | Native Resource；读 [resource.md](references/resource.md) |

能力查询和任务结果都有 `backendResponse`，这是后端原始结果；`ok`、退出码和实际回读必须一致。外层或后端报告失败时停止，检查失败证据。没有收到回执代表结果待核实，不自动重发操作、强杀或关闭用户程序。

`m2-event-evidence` 通过同一入口的 `--adapter m2` 调用，需要 Native Control 1.1.12+ 且 manifest 声明该命令。它只采集指定 M2 原版的固定 DFM、VMT/published table、三个 handler 及一个固定共享后继 callee 的入口证据，不触发 GUI；先读专项合同。共享后继是独立 callee，不是第四个 DFM 事件；profile 与请求 JSON 保持不变，不开放任意地址。无需新 EXE、常驻后台或另写读取脚本。旧版适配失败会明确返回版本或 manifest 错误，不自动回退到缺少共享后继证据的 1.1.11 或更旧载体；Native Control 1.1.9 的普通 M2 命令仍按原门槛调用。

## 观察、操作、确认

1. 现场确认目标：完整路径、EXE SHA256、当前 PID、窗口类名/标题和唯一性；历史 PID/HWND 只供追溯。
2. 读取当前状态。原生窗口用 `window-observe` 取得截图、控件树和完整菜单路径，实际查看图片；游戏用 `game-observe`。每个原生动作绑定该次观察回执及 SHA256。
3. 执行一个有明确目的的动作。坐标必须来自刚查看的目标客户区；弹窗、窗口尺寸、前台或目标变化后重新观察。
4. 验证用户要的结果。控件设值后点击原生保存，比较落盘文件的完整差分，再按任务重读并重新加载页面回读；输入送达或控件文字变化不能替代保存。游戏读取新截图，资源读取输出与回执。
5. 留下必要回执和截图。游戏适配器自动核验鼠标/原前台恢复；旧原生工具按自己的实例关闭与来源保护合同恢复，不冒称具有统一焦点恢复能力。

运行中窗口、目标或地图变化时停止使用旧坐标。游戏角色通常固定在画面中心，场景随跑动滚动；返回旧屏幕点不能证明返回原地图坐标。战斗可能由一次点击触发自动连击，先观察结果再决定是否补输入。

LoginSrv 窗口支持需要 Native Control 1.1.15+，使用 `engine` 及原窗口请求；固定版本、宿主校验与验证边界见 [window.md](references/window.md)。业务保存与重新加载须由具体任务验收。

DBServer、RunGate、SelGate 窗口支持需要 Native Control 1.1.16+，也使用 `engine` 与原窗口合同；实际日志或网关表内容须从当前截图/原生控件核实，工具维护不代执行业务诊断。

微端服务器 UpdateServer_x64 与微端网关 MirUpdateGate 的候选适配见 Native Control 1.1.21，沿用 `engine` 和原窗口请求；固定指纹、读取与保存路径、敏感数据及验收边界见 [window.md](references/window.md) 末节。是否已发布以正式 manifest 为准。

## 当前验证边界

- 游戏仅支持已验证的 `D:\Mirserver100\LabClient\LFM2-100-LAB.exe`；其他路径/版本先作专门适配。文本/聊天粘贴未开放，已有中文乱码实测。
- Native Control 1.1.9 的 `window-observe` / `window-action` 开放 M2、GameCenter、MakeGameLogin 和原版 WZL/PAK 编辑器的现场控件操作；不再限于 `engine-parameter` 的人数间隔预设。使用 `m2/engine/launcher/editor`，游戏接口仍只操作游戏。
- Native Control 1.1.12 的 `m2-event-evidence` 仅支持专项合同固定路径和 SHA256 的 M2 主模块；DFM 绑定、published table 地址关系和四份原始片段分别记录。共享后继固定 RVA `0xFD1F30`、512 bytes，须按现场实际模块基址重核 VA，并保留全部同址 published 匹配（0、1 或多项；0 仅表示已校验表内未找到）。原始 `*.entry.bin` 是权威来源，标准 AMD64 `.analysis.dll` 仅供 REA/Ghidra 静态导入；工作流绝不加载或执行载体，REA 实际打开及共享后继指令读取另行核验。不能据此宣称当前实例的 `OnChange` 运行指针、完整函数、跨片段调用或分支关系、`EnabledCallMonster` 派生规则已确证。`GlobalVal.ini` 仅观测，业务实验及改值另行授权。
- 窗口通用动作证明工具可以操控现场控件；各业务字段的含义、保存映射和游戏效果分别验收。已授权的编辑任务可直接执行字段、保存、重读链，不逐点击重复求确认。
- `engine-parameter-cycle` 和整套 `engine-start/engine-stop` 属于旁边的未发布候选，本入口没有合入；不得遍历历史证据自动选最高版本。
- WZL/PAK 操作使用原版独立副本，产物安装属于具体业务任务；源保护/解析/哈希成功与游戏资源显示验收分别记录。

新窗口可直接输入 `$xuanyuan-native-control` 后接具体目标。若该会话的技能列表尚未刷新，先读取本文件继续；必要时重启 Codex 发现新技能。


Native Control 1.1.22 的确定后隐藏结果见 [window.md](references/window.md) 对应章节；target=null 的结果不可作为下一次输入凭据。是否已安装以正式manifest为准。


Native Control 1.1.23：GameCenter宿主类名兼容修复
继续使用原invoke.py及m2/engine的window-observe/window-action；不新增控制器或业务接口。宿主仅接受TfrmMain、TFrmMain两个精确类名，其他大小写及未知类仍拒绝。固定SHA、同根路径、PID/创建时间、完整父链、可见启用、观察回执、焦点和输入归属校验保留；观察后在两类名间变化仍使旧回执失效。
本轮为类名准入缺陷离线回归及同源发布，未操作业务GUI、重读QFunction、启用检测或启停引擎。主窗宿主关系、菜单重读与业务效果由原任务使用新观察继续验证，不因class修复宣称业务成功。1.1.22隐藏后置回执协议保持；旧m2-reload隔离根限制保持。


Native Control 1.1.24：原window-action新增minimize
仍使用原invoke.py，DBServer用adapter=engine。先对DBServer自身PID/HWND/完整EXE及SHA做新的window-observe，实际核对该窗口截图与hosting；随后以该回执和SHA提交window-action，action仅为{"kind":"minimize"}（可选原settleMs）。不可把GameCenter父窗回执或跨PID标题栏坐标当作DBServer凭据。
仅对可见、启用、未最小化、无模态阻挡且有完整标题栏、系统菜单和最小化框样式的已验证窗口派发一次WM_SYSCOMMAND/SC_MINIMIZE；发送目标是该窗口自身HWND，不能用宿主rootHwnd代替。固定指纹、同根、PID/创建时间、宿主与父链、新观察/原值及焦点/点位保护保留。原前台若就是待最小化的独立窗口则派发前拒绝，避免恢复前台与维持最小化冲突。
ACK只表示处理返回，必须核对实际IsIconic状态及窗口身份；恢复原前台和鼠标后再次核验仍最小化，readbackVerified=true才表示UI最小化回读通过。程序忽略命令、窗口消失/身份变化或恢复撤销最小化均失败，不自动重发。最小化后screenshot可为null；这不代表关闭，更不代表服务停止、落盘保存或业务重读。恢复窗口沿原show动作及新观察合同。
本轮只做离线Win32边界回归、冻结源及发布核验，没有操作现场DBServer、重读物品/QFunction、启用检测或启停组件。现场最小化、遮挡解除与业务效果由原任务继续验收。996仍暂停。
