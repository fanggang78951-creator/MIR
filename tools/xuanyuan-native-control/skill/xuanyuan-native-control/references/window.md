# 原生窗口、控件与自绘区域

用 Native Control 1.1.9 的 `window-observe` / `window-action` 操作现场 M2、GameCenter、MakeGameLogin 或原版 `Wzl编辑器.exe`。适配器分别为 `m2`、`engine`、`launcher`、`editor`；都经过统一路由器、EXE/manifest 核验和桌面互斥。游戏继续使用 `game`，批量图片导入导出继续使用 `resource` 的既有后端。

LoginSrv 使用 Native Control 1.1.15+ 和 `engine`；详细固定版本与宿主规则见本文末节。

DBServer、RunGate、SelGate 使用 Native Control 1.1.16+ 和 `engine`；固定版本与本轮验证边界见本文末节。

这是按现场控件操作的通用接口，字段不必逐个加入 `engine-parameter`。它不会自动判定业务值是否正确，也不会把按钮点击成功当成保存或游戏验收。

## 观察与身份

先用 `inspect`（M2/GameCenter）或现场进程枚举取得目标路径、PID、窗口 HWND/class/title，并核对当前原版 EXE 的 SHA256。正式端和实验端并存时用用户指定的完整根目录选定目标。每次 `outputRoot` 为尚不存在的独立目录，位于 `policy.allowedWriteRoots` 内。

通过统一入口提交如下请求。数字、SHA256、窗口类名和标题均替换为现场值，不能直接复用示例：

```json
{
  "schemaVersion": 1,
  "command": "window-observe",
  "arguments": {
    "pid": 32096,
    "hwnd": 123456,
    "expectedExecutable": "D:\\Mirserver100\\Mir200\\M2Server.exe",
    "expectedSha256": "REPLACE_WITH_CURRENT_EXE_SHA256",
    "expectedClass": "REPLACE_WITH_CURRENT_WINDOW_CLASS",
    "expectedTitle": "REPLACE_WITH_CURRENT_WINDOW_TITLE",
    "outputRoot": "D:\\任务目录\\observe-001"
  },
  "policy": {"allowedWriteRoots": ["D:\\任务目录"]}
}
```

读取 `backendResponse.data` 的 `target`、`forms`、控件树、菜单完整路径和截图，实际查看图片后决定动作。`observationReceipt` 是生成的 `observation.json` 绝对路径，`observationSha256` 是其 SHA256；两者使用返回值，不推导文件内部未写出的自身哈希。独立顶层隐藏窗口的 `screenshot` 为 null，此时只可执行 `show`，再观察可见画面。M2、LoginSrv、DBServer、RunGate 或 SelGate 若嵌入 GameCenter 的页签，应先观察并选择宿主页；不能把未选宿主页等同于普通隐藏窗口。

新对话框出现后，从 `forms` 选其现场 HWND/class/title，重新 `window-observe`，将后续控件动作绑定这个对话框。`controlHwnd` 必须属于当前目标的控件树。主窗已禁用或被模态框阻塞时，不继续对主窗发动作。不能凭无标题输入框的邻近位置猜业务字段；结合当前页面、组框、截图与已验证的保存映射定位。

普通未适配的 child form 仅允许观察；不能因为观察成功就对它发送输入。M2 及固定版本 LoginSrv/DBServer/RunGate/SelGate 的 GameCenter 宿主属于专门校验的适配，须按现场宿主身份和父级链核对；不能把这一例外推广到任意跨进程父窗。宿主页选择文字和位置取自当前 GameCenter 观察，不使用历史 HWND、示例页名或固定坐标。

宿主适配不增加请求字段。观察的 `target.hosting` 为 null、`kind:'GameCenterHostedM2'` 、`kind:'GameCenterHostedLoginSrv'`、`kind:'GameCenterHostedDBServer'`、`kind:'GameCenterHostedRunGate'` 或 `kind:'GameCenterHostedSelGate'` 对象；后者记录宿主 `rootHwnd/pid/class/title/executable/sha256/processCreated/visible/enabled/minimized` 以及完整 `ancestorChain`。只接受目标 M2、LoginSrv、DBServer、RunGate 或 SelGate 同根、原版哈希已验证的 GameCenter `TfrmMain`，回执绑定此宿主身份与实际父级链。即使前台归 GameCenter，视觉动作仍须命中经过目标 M2、LoginSrv、DBServer、RunGate 或 SelGate 的窗口归属链，按键焦点须在该目标后代；不把 GameCenter 的其他页当该目标操作。

嵌入的 M2、LoginSrv、DBServer、RunGate 或 SelGate 不可见时 `show` 会拒绝。先以 `engine` 对真实 GameCenter 做 `window-observe`，从其当前可见 `TPageControl` 的真实页签选择目标宿主页，再以目标自己的 PID/HWND/EXE 指纹做新的 `window-observe`。控件树只列当前目标同 PID 的子控件，跨进程 M2、LoginSrv、DBServer、RunGate 或 SelGate 需作为独立目标观察；不从 GameCenter 控件树猜其字段。

## 单次动作合同

观察在 120 秒内有效。保留目标身份字段，命令改为 `window-action`，改用新的 `outputRoot`，增加 `observationReceipt`、`observationSha256`、`action`。动作成功也返回新的观察回执，可作为下一次动作的绑定；目标或页面变化后重新核实控件和截图。

| `action.kind` | 其余字段 |
|---|---|
| `show` | 无；显示/恢复目标窗口，含托盘隐藏窗口 |
| `menu` | `path`：逐层精确 caption 数组；`synchronous` 可选，默认 false |
| `set-text` | `controlHwnd`、`expectedClass`、`expectedText`、`value`；文字原值须一致 |
| `select-combo` | `controlHwnd`、`expectedClass`、`expectedIndex`、完整 `expectedOptions` 数组、目标 `index` |
| `select-tab` | `controlHwnd`、`expectedClass`、`expectedSelection`：原页 caption、`text`：目标页 caption |
| `button` | `controlHwnd`、`expectedClass`、`expectedText`；复选框可加 `expectedCheck`（0/1/2）；`synchronous` 默认 true |
| `close` | `synchronous` 可选，默认 false；关闭当前目标窗，用于明确结束当前已处理页面 |
| `visual-click` | `x`、`y`：目标客户区点，`button`：`left` 或 `right`；用于现场观察过的自绘区域 |
| `key` | `key`：HOME/END/UP/DOWN/LEFT/RIGHT/PAGEUP/PAGEDOWN/ENTER/ESC/TAB/F1..F12 |

全部动作可选 `settleMs`（0..3000）；视觉点击/按键可选 `holdMs`（0..1000）。每次只执行一个动作，不自动重试，不自动确认未知弹窗。要打开模态框的按钮可用 `synchronous:false`，随后观察新窗。菜单默认单次 PostMessage，`handlerAcknowledged:false` 仅表示提交；需要确认菜单处理结束时显式 `synchronous:true`，工具以最长 60 秒 SendMessageTimeout 等待 ACK，超时后检查证据与现场，不重发。

`close` 默认也仅提交一次 PostMessage，随后检查是否实际关闭或出现保存确认；有确认框时重新观察，不自动确认。`set-text`、`select-combo` 和普通 `select-tab` 的期望值需原生回读匹配，结果 `readbackVerified:true` 才能称控件操作成功。观察标有 `textTruncated` 的编辑字段不可执行 `set-text`；TCS_BUTTONS 样式的特殊页签使用新观察下的 `visual-click`，不以普通页签消息假装切换成功。

例如，对刚观察到的输入框设值：

```json
{
  "kind": "set-text",
  "controlHwnd": 234567,
  "expectedClass": "TSpinEditEx",
  "expectedText": "0",
  "value": "1"
}
```

动作点来自刚查看的目标截图。若截图包含窗口边框，用观察中的 `clientOrigin` 和 `rect` 把截图点换成客户区点；不可混用屏幕坐标。切页、窗口大小/位置、弹窗、前台或控件变化后重新观察。自绘控件在截图里可见但无文字语义时，使用原生视觉动作完成选择，再观察载入的字段；不虚构树控件按名称搜索接口。

## 自定义怪物：字段、保存、重读、GUI 回读

以用户授权的 100 测试端独立夹具为例。当前夹具为 `LFM2Probe1810`，列表第 0 行，Race/RaceImg=156、Appr=30000；这些是示例证据，实际任务仍检查当前记录，不把第 0 行永远当该怪物。目标 INI 位于所选服务端的 `Mir200\Envir\SmartMonster`。执行前保存其原始字节和哈希，并明确此次字段、目标值和恢复方式。

1. 观察 M2 主窗。独立隐藏主窗先 `show`；嵌入 GameCenter 时先用 `engine` 观察并选择实际 M2 宿主页，再用 `m2` 观察。按实际菜单 caption 打开怪物设置，当前版本路径为 `['选项(&P)','怪物设置(&G)']`。使用菜单默认异步打开，观察返回的 `forms`；重新绑定 `TfrmMonsterConfig` / `怪物设置` 对话框。
2. 用 `select-tab` 切到外层 `自定义怪物` 页，再按所需字段切内层 `客户端动作及特效` 或 `服务器端攻击/增益` 页。所有原页/目标页 caption 取自本次控件快照。
3. 在 `怪物列表` 的 `TVirtualStringTree` 实际点击记录行并观察字段载入。当前夹具在首行，可让列表获得焦点后按 HOME，再实际点击截图中的首行。只发 HOME、选中高亮或双击事件不能证明编辑字段已加载；须核对名称与字段新值。
4. 在 `客户端动作及特效` 页的 `怪物名称设置` 组中，当前两个可见 `TSpinEditEx` 按 top、left 顺序为名称偏移 X/Y，映射 `[ClientConfig] NameOffsetX/NameOffsetY`。用 `set-text` 提交原值到目标值。服务器页基本设置的怪物类型组合框完整选项为 `['普通怪物','石化怪物','苏醒怪物']`，映射 `[ServerConfig] MonsterType`；用 `select-combo`，同时绑定当前 index 与完整选项。仅当现场页面和控件匹配时采用该映射。
5. 观察编辑结果，点击 caption 精确为 `保存` 的原生按钮。每次请求使用新的观察回执。读取目标 INI 的完整差分，确认节、键和值；不要只核对一个已知键后忽略其他变化。旧格式文件的首次原生保存可能补写 45 个缺失键，不能把它们默认为等价默认值或算作新字段验收。保存有未解释的附带变化时保留全部证据，按任务范围恢复或复核。
6. 关闭当前设置页，重新观察并绑定启用的 M2 主窗，提交如下菜单动作，要求 handler ACK：

```json
{
  "kind": "menu",
  "path": ["控制(&C)", "重新加载(&R)", "怪物数据库(&M)"],
  "synchronous": true
}
```

7. 再按步骤 1..3 打开、切页并实际加载同一记录，用控件快照和截图核对 X/Y 或类型的目标值，保存回读证据。完整 INI 差分证明落盘，handler ACK 证明菜单处理返回，GUI 回读证明该页面再次呈现该值；三者分别记录。它们不能独立证明活动怪物、客户端缓存或战斗效果已改变。

这是实际字段设值→原生保存→完整文件差分→怪物库重读→GUI 再加载回读链。`engine-parameter` 的人数间隔项目不参与此链，也不作为新增字段验证。

验证性往返实验恢复时，先在同一 GUI 记录把字段反向设置为原值并点击保存，核对反向差分；若还需恢复首次保存补写等差异，再恢复备份的精确原始字节。随后怪物数据库重读并重新加载该记录，确认 GUI 原值和文件原哈希。仅覆盖磁盘后看仍打开的页面会被缓存误导；只关开页面也不能替代文件检查。用户要求保留业务修改的正式任务，则按其目标值保存并验收，不擅自把成功业务修改回滚。

## 结果与恢复

`backendResponse` 保留原后端结果；以 `ok`、退出码和实际证据共同判断。动作结果中的 `target/forms/screenshot/recovery` 便于继续观察和核对桌面恢复。失败可能在真实输入后发生，未收到成功回执时先检查窗口和文件；不自动补一次相同点击。保留失败回执及其 observation，不将恢复失败或未知弹窗解释为任务成功。

2026-10-19 Native Control 1.1.13：原版文件对话框子框识别修复
同一工具/同一技能入口，window-observe/window-action请求字段和身份/回执/互斥不变。文件对话框内部带WS_CHILD的#32770保留在forms/controls中，但不再作为独立owned modal阻挡父文件框；不按零宽/面积放行，真正的owned modal继续阻止父窗输入，普通child form输入保护保持。
最终EXE实测：可见“打开”框含零宽WS_CHILD时截图成功；文件名set-text同步ACK及回读通过；打开任务WZL后重新观察原版主窗显示0/1799。475测试/162子测试通过，13冻结模块匹配。没有重验M2/游戏业务效果。
原有恢复限制保留：若动作关闭了调用前的原前台HWND，可能已投递/关闭但因无法恢复该前台而返回失败。此时查outputRoot/failure.json并重新观察现场；失败不等于未动作，绝不自动重发，不能把该命令称整体成功。
资源批处理继续adapter=resource、Native Resource1.0.1。当前PAK237导出、三张55x55尾部追加/原版回读、供体1905及WZL追加回读通过，源文件未变；旧TimeoutError本轮未复现，根因未确认，未修改Resource代码。导入图inputRgbEqual=false，不能称无损或透明显示已验收。资源输出只在任务副本，业务安装另行授权。

2026-10-19 Native Control 1.1.14：TRzButtonEdit设值支持
仍调用统一正式入口invoke.py，adapter=launcher/editor/m2/engine与window-observe/window-action合同不变。原set-text类白名单新增TRzButtonEdit；先新观察取得当前controlHwnd/expectedText，再以expectedClass=TRzButtonEdit和任务批准的value提交。沿原同步WM_SETTEXT及WM_GETTEXT回读，保留120秒回执/指纹/原值/父窗/owner/样式/可见启用/焦点与恢复校验，不新增路径旁路或自动选择按钮。readbackVerified=true仅说明控件回读；原生保存、完整落盘差异与重新加载由业务任务验证。
完整491测试/162子测试通过，新增16例及相关139例通过，13冻结模块一致；产品仅白名单及VERSION变化。本轮未读取或操作PID30716及大画布，真实TfrmGUI路径设值由原施工窗口继续验收，不将边界测试当作实窗验收。
close协议未改。ui14的actionAttempted=true/posted后才发生观察准入错误，原窗口已确认close实际执行；不要重发。隐藏TfrmGUI可能被后置forms过滤，错误不代表输入前拒绝；同样保留关闭原前台后的恢复失败限制。失败时检查failure.json、重新观察，不自动补点击。

2026-10-19 Native Control 1.1.15：固定版本 LoginSrv 窗口支持
仍使用统一 invoke.py，LoginSrv 走 adapter=engine，沿用 window-observe/window-action 请求，不新增命令、适配器或业务参数接口。LoginSrv.exe 指纹复用 native_engine.STACK_BINARIES 权威项；当前支持 SHA256 为 1CC15D5A3848E2EB3DD2FB52947331527D8708C165F3266D5AC7DA80C8D9BC57。
嵌入 GameCenter 的 LoginSrv 回执 hosting.kind 为 GameCenterHostedLoginSrv；M2 继续为 GameCenterHostedM2。只接受同根原版 GameCenter TfrmMain 和完整现场父级链，链上 PID 只能属于目标与宿主。独立 LoginSrv 的 hosting 为 null；独立窗仅在原观察准入合同可枚举时使用 show，其他隐藏类未验证；隐藏嵌入主窗须先观察 GameCenter 并选择实际宿主页。窗口或页签变化后重新观察，历史 PID/HWND 不作调用依据。
可按现场原生控件使用既有设值、按钮、菜单与回读操作。工具不内置二级密码开关语义，不假设修改单个 INI 键等价于原生保存。业务窗口负责备份、原生保存、完整落盘差异、重新加载回读及实际业务验收；账号、口令和数据库不属于本次工具回归输入。
本次完成单元及 Win32 边界模拟回归、冻结模块一致性与正式统一入口能力查询；未启动旧服务端 seed、未操作正式 LoginSrv 窗口、未测试真实基础设置保存、未重启组件，也未修改正式业务配置。通过测试不代表二级密码业务已取消。原 close 恢复限制保留，失败时先查 failure.json 和现场，不自动重发。

2026-10-19 Native Control 1.1.16：固定 DBServer/RunGate/SelGate 窗口支持
仍使用统一 invoke.py 的 adapter=engine 和 window-observe/window-action，原 JSON 请求、回执、桌面互斥和动作合同不变。不新增工具、适配器、解析器、业务参数或日志/网关分配表接口；原窗口截图、原生可枚举文字与已有菜单/控件动作供具体任务按现场读取，自绘表格不保证有结构化文本。
三个 EXE 均从 native_engine.STACK_BINARIES 取得唯一权威指纹。当前 DBServer.exe 为 06DA830E181A7DFDD913A4D322422AD01C755C8A105CA69AE08A7716C25DC6BE，拒绝旧 BINARIES 的 8686 版本；RunGate.exe 为 F6494D1A560D9D7D4B2A7BB8EAAEB24D4B38ECE39A84D0630E35E0C3CE23FDC4；SelGate.exe 为 4A707773A3AB6CBC93A0C0239B8DCED39EFDD07F31D70DBF50F417EC022E3E55。未将 LoginGate 或 LogServer 加入原窗口白名单。
新增 hosting.kind 分别为 GameCenterHostedDBServer、GameCenterHostedRunGate、GameCenterHostedSelGate；原 M2/LoginSrv kind 保持。只接受各目标同根、固定版本 GameCenter 的 TfrmMain 与完整现场父窗链，链上仅允许目标和宿主两个 PID。目标控件仍须同 PID，回执、前台、焦点和未选宿主页保护不变。隐藏嵌入窗先观察 GameCenter 并选择实际宿主页，再单独观察目标；独立窗仅在原观察准入合同可枚举时可用 show，其他隐藏类未验证。历史 PID/HWND 仅追溯，使用前重新枚举。
本轮为工具维护与离线回归，未操作正式窗口、未执行网关设置/选择网关或其他菜单、未重载或启停服务、未另开服务或沙盒、未读取账号/人物库或凭据、未改业务配置，也未触生成器大画布。单元及 Win32 边界模拟、冻结模块和正式入口查询结果见同目录 manifest 绑定证据；真实三组件窗口内容/日志/网关表尚由业务窗口继续只读验收。工具发布不能证明选角故障根因或已经修复，不把一次连接或 TIME_WAIT 当故障结论。原 close 恢复限制保留，失败先查证据和现场，不自动重发动作。

2026-10-19 Native Control 1.1.17：TJvInspectorEdit 设值支持
仍调用统一 invoke.py，MakeGameLogin 属性编辑用 adapter=launcher 和原 window-observe/window-action。仅原 set-text 编辑类白名单新增精确 TJvInspectorEdit，不新增命令、适配器、按键、内存写入或控制实现。请求字段不变：从新观察取得实际控件 HWND、expectedClass=TJvInspectorEdit 和 expectedText，value 为本任务授权值；历史 HWND 不得直接输入。
沿原同步 WM_SETTEXT ACK 及 WM_GETTEXT 回读，保留新观察回执/哈希/120秒时效、固定EXE与进程、目标/控件类与原值、父窗/owner/style、可见启用、同PID控件、焦点和恢复校验。回执 readbackVerified=true 只证明编辑框文字匹配；不证明 TJvInspector 已提交业务属性。属性提交、离开编辑后重观察、原生保存、完整落盘差异、重新加载属性回读与游戏验收，由原施工窗口按具体任务完成，不能把控件输入成功当作人物面板已保存或安装。
本轮只检查已有离线观察中的类身份、任务生成器EXE静态指纹，并做模拟OS边界回归/冻结一致性/正式入口查询；没有操作任务生成器实例或画布、正式端、M2或客户端，没有修改或安装任何业务文件。实际 TJvInspector 属性提交和保存未在维护窗口重验。测试计数及发布状态见同目录 manifest 绑定证据；原 close 与前台恢复限制不变，失败先查 failure.json 和现场，不自动重发。

2026-10-19 Native Control 1.1.18：原失败回执 guardEvidence
统一 invoke.py、适配器、window-observe/window-action 请求与输入能力不变，TJvInspectorEdit 支持保留。只在既有 failure.json 附加 guardEvidence，不新增探针、诊断命令、按键或业务接口。原进程/窗口/回执/权限/父链/同PID/焦点和恢复校验不放宽。
guardEvidence 记录最近一次原生窗口守卫的 stage、pointScreen、requestedClientPoint、targetHwnd/targetRootHwnd、既有 clientOrigin/clientSize、requireMembership、firstFailedCheck，以及按原短路顺序实际读到的 foregroundBefore、pointRoot、foregroundAfter；未执行的查询记 null。stage 区分 initial-center、fresh-center、pre-move、post-move、capture-before、capture-after；同一原派发前检查在 key 未移动时标为 pre-input，不增加检查次数。未到守卫时 stage 及未观测字段为 null；若最近守卫通过而后续因身份等其他错误失败，firstFailedCheck 为 null，不能把它误读成守卫失配。firstFailedCheck 非空时对应 foregroundBefore、pointRoot、foregroundAfter、observationMembership 或 inputMembership。pointerMoveAttempted/pointerMoveVerified 只记录原请求中的目标光标移动是否调用及成功返回，不包含 finally 的恢复移动，不新增光标查询。
三项根窗口比较、原祖先/同PID检查的查询顺序、次数、立即拒绝与错误文本/类型保留；证据只复用原查询返回，不事后补查冒充失败瞬间，不自动重发。该补充帮助区分前台变化、点命中根不同及守卫阶段，不代表已证明或修复 DPI、遮挡或屏幕范围根因。
actionAttempted=false 只表示尚未进入该动作的派发，不能据此笼统说没有激活或移动；点击的 down/up 未执行仍可能已经 move，随后执行恢复。visual-click 的 actionAttempted=true 且 dispatch.mode=SendInput/accepted=true 表明点击已发送；若随后标题随对象选择变化，原身份复核仍可拒绝，失败不等于点击未发生。例如既有 character-basiccanvas59 正是派发后身份复核错误，不能自动重发。搜索选中树节点也不能证明 Inspector 已加载或几何已提交。业务属性、原生保存、完整差异、重开回读与游戏验收继续由具体任务完成。
本轮仅模拟边界回归、冻结核验与正式入口查询，未操作任务画布、目标窗口、正式端、M2或客户端，未保存/安装业务文件或启停引擎。真实现场失配仍需施工窗口基于新观察按既有授权安排单次动作并检查回执；测试计数和状态以 manifest 绑定证据为准。

2026-10-20 Native Control 1.1.19：TJvInspectorMemo 与多行标题
仍用统一 invoke.py 的 adapter=launcher、原 window-observe/window-action 与 set-text 请求。编辑类白名单仅新增精确 TJvInspectorMemo；不能把它当 TJvInspectorEdit 或相似类，也不新增控制器、命令、按键、消息路径或直接业务二进制修改。每次先新观察取得当前目标/控件及原值，历史PID/HWND仅追溯。
既有派发按控件原生样式选路径：带 ES_MULTILINE 位的编辑框使用原 EM_SETSEL(0,-1)→EM_REPLACESEL(1,value) 通知序列；单行分支仍用同步 WM_SETTEXT。随后沿原 WM_GETTEXT 回读并逐字比较。当前离线 TJvInspectorMemo 样式含多行位，所以实际适用前者；并非新增或改成纯 WM_SETTEXT。同步消息、单次动作、原值、回执/指纹/时效、进程/父链/同PID/类/样式/可见启用/焦点/恢复、长度/NUL/截断拒绝均保留，1.1.18 guardEvidence 不变。
value 可包含中文及实际LF或CRLF换行，标准JSON示例：
{"value": "装\n备"}
{"value": "装\r\n备"}
请求与回读不自动转义、trim或规范化换行；不能把两个字符的反斜杠加n当实际换行。若原版控件规范化LF/CRLF导致与请求不符，原精确回读仍拒绝，不自动重发；业务窗口检查实际回读再使用原生格式。Windows多行标题可优先按CRLF示例提交。
模拟OS消息测试只证明原文派发及同步文字回读路径，不证明真实 Memo 已完成换行规范化、Inspector标题提交、原生保存、资源安装或游戏显示。属性提交、离开编辑后新观察、原生保存、完整差异、重开回读与游戏验收由原施工窗口完成。本维护未操作任务画布、实时生成器、正式端、M2或客户端，未保存或安装任何业务文件。失败先查failure.json、guardEvidence和现场，不自动重发；工具发布不代表人物面板已修复。

2026-10-20 Native Control 1.1.20：原生 tooltip 模态误分类修复
仍用同一 invoke.py、adapter=launcher/engine/m2/editor 与原 window-observe/window-action。仅修原 snapshot 的 blockingWindows 判定：同PID已枚举窗中，精确 class=tooltips_class32 且带 WS_POPUP 的标准提示窗不再作为独立模态阻塞；forms 及其类、owner、parent、style等元数据完整保留。不增加探针/API/消息、请求字段、控制器或关闭提示的自动动作。微软标准tooltip说明其带WS_POPUP及WS_EX_TOOLWINDOW：https://learn.microsoft.com/en-us/windows/win32/controls/tooltip-styles
本例anchor-dress20/21原blockingWindows仅有tooltips_class32；SysShadow只在forms、parent/owner均0，未参与本轮阻塞，故未新增SysShadow豁免。近似类名、大小写变体、非WS_POPUP同名窗、未知owned popup、自定义警告及真实#32770仍按原规则判断，不按面积小、空标题或目标enabled就泛化放行。WS_CHILD文件框子窗的既有区分保持，目标禁用、未恢复、真正模态、进程/父链/同PID、观察回执/哈希/时效、前台/焦点/点归属及恢复校验均不变。
原截图和动作守卫不变：提示窗若实际覆盖截图中心或操作点，原WindowFromPoint/归属检查仍可拒绝，不提供穿透点击。此修复只消除错误的模态列表项，不保证任何遮挡情形下都可继续。1.1.18 guardEvidence及1.1.19 Memo精确多行回读保留。
使用新工具后先重新window-observe并实际查看截图，再按原任务发单次动作；历史PID/HWND和旧观察不可直接复用。不自动ESC、关闭气泡、点击、重试或确认弹窗，失败先查failure.json/guardEvidence和新现场；actionAttempted=true不等于未输入。
本轮通过离线观察证据、模拟OS边界回归、冻结源一致性和正式入口能力查询验证；未操作任务画布、实时生成器、M2、客户端或业务文件，未验证现场tooltip解除后的业务操作。真实新观察、属性提交、原生保存、重开回读与游戏验收由原施工窗口继续。测试计数和发布状态以manifest绑定证据为准。

2026-10-22 Native Control 1.1.21：微端服务器与微端网关
复用唯一已安装 invoke.py，二者都用 adapter=engine 和原 inspect/window-observe/window-action，不新增控制器、适配器、整引擎命令或长期调用入口。仅固定版本 UpdateServer_x64.exe（AMD64，SHA256 2FE71E3C8ED9FD113A392EBC50D603396412DEBD6DEC6CBCEEFC785646055DE2）与 MirUpdateGate.exe（x86，SHA256 2F12AB71F0D35D4259F96C2CCBA77F5DC8239BF0B3705654457F59D27CFB26B5）纳入原窗口适配；不泛化到其他同名版本。按现场完整路径、当前PID、HWND、实际类名/标题和指纹绑定两个独立顶层窗口，不适用 GameCenter 跨进程宿主例外。
先用已有 inspect 请求（schemaVersion=1、command=inspect、arguments={pid,expectedExecutable}）核对实际路径、返回的 executableSha256 和当前原生窗。inspect 是只读枚举，保留旧的有限控件筛选；它不产生完整控件树、截图或动作观察回执，不能作为后续输入绑定。完整读取仍用 window-observe：arguments 含 pid/hwnd/expectedExecutable/expectedSha256/expectedClass/expectedTitle/outputRoot，policy.allowedWriteRoots 限本任务；以当前窗口实际值替换，不直接复用历史PID/HWND。
字段沿原 set-text 和原值/精确类名回读；本候选只增补精确 TRzEdit、TRzMaskEdit 原生编辑类，并为 TRzCheckBox 观察 check 状态，不包含任意相似类。TRzPageControl 不纳入普通 select-tab；TRzBitBtn、TRzCheckBox 不纳入 button 动作。本轮实窗发现：截图可见三页而通用TCM返回tabs=[]，BM_CLICK虽有ACK却未触发这些自绘按钮/复选框的业务动作，不能把ACK当已点击或已保存。它们按当次目标截图显式提交原有 visual-click，再用新快照的 check/截图和文件差分验证；原标准控件的既有动作合同保持。此路径是调用任务基于新观察选择的明确单次动作，不是button/select-tab失败后的自动fallback、重发或伪造类名。网关有“日志/配置/关于”、条目地址/端口/关键字、组别、添加/修改和基本设置保存；静态控件名/事件及一次设值成功不证明完整字段落盘、重开或业务验收。
服务器设置页、所有文件的 Pak 页/筛选/载入密码与保存，都按实窗可枚举的原生控件、完整菜单或当前截图执行单次动作；不虚构逐行列表接口。出现原生文件框后从 forms 绑定该框的新观察，用原 Edit 文件名设值及“打开”按钮；不得绕过真实模态继续对父窗输入。保存后比较本任务授权文件的完整差分，再按业务流程重开/重载并回读，输入ACK、控件文字或单次保存点击都不等价落盘/下载/解密验收。
日志 TMemo/TRzMemo 等仅在原生窗口文字可读时随 controls.text 返回，textTruncated=true 表示不完整，不能称全量日志。自绘树、列表或网格可能只有截图，没有结构化逐行内容；按本次实窗证据记录覆盖，不把空文字当空列表，不新增全量日志或任意内存读取接口。
原模态、WS_CHILD、禁用目标、进程/窗口指纹、同PID/父链、原值、观察哈希/120秒时效、焦点/点归属及恢复保护和 guardEvidence 保持；不自动确认弹窗、关闭气泡或重发。没有新增微端专用启停命令；生命周期操作仅限具体任务明确授权的本机测试实例，启动副本需独立配置、工作目录、资源目录和不冲突的loopback端口，并核对实际监听及恢复。此适配不授权改当前业务配置、重启现有服务、操作整引擎/远端或覆盖公共资源与登录器配置。
真实密码表只由获授权的业务任务按文件路径交给原生导入，不为排错读取、粘贴或在消息/普通日志中回显密码。完整观察可能含控件文字和截图，本节不承诺按业务含义自动脱敏；敏感证据及完整文件差分须由具体任务保护。本轮工具测试只使用公开合成数据，不复用真实 ui8 密码表，也不把空表/合成导入当有效 Pak 解密、真实密码或业务下载验收。
本轮隔离服务器副本已实测设置页的复选框、TEdit、Combo 设值、原生保存和重开字段回读。完整 INI 差分包括应用将 MaxPreAllocatedMemoryCount 从16钳制为4096（初始界面即显示4096），以及4项 LogData 目标变更；这项原生保存写回已纳入差分记录，不能只凭预期字段判断保存范围。
所有文件的 AllFiles/Wzl/Pak 页切换和筛选后的行隐藏/恢复已实测。明文单元格经 F2 出现 TEdit，设公开合成密码后按 ENTER 提交，再用原生 Save 生成165字节 pak.txt；重开后 Pak 密文列可见且落盘哈希一致，完整哈希见绑定证据。这仅验证该合成单元格的编辑、保存与重开，不证明有效 Pak 解密或业务下载。
TXT 载入的原生文件框打开、文件名设值和“打开”已实测，但两个非空合成样本（相对路径|明文、原生完整路径|密文）均匹配0项，Save 仍禁用。非空 TXT 导入的匹配/应用语义尚未验收，不能称密码导入完成；本轮未读取真实密码表。
网关隔离副本已实测 TRzMaskEdit 设值、select-combo 选择高防组，以及 visual-click 修改/保存触发原生成功提示并落盘。基本设置重开后 GatePort=17090、ShowLog check=1，实际监听127.0.0.1:17090；原生日志返回2行且未截断。高防组条目重开后端口18081、组别 selectedIndex=1 已回读。关键字却实测出现首字符变化：首次 NC211 重开为 C211；最终保存文件为 NC211B，重开树和 TRzMaskEdit 均为 C211B，因此关键字持久化未通过。原值不符时 guard 拒绝有效，不能绕过该保护或把保存成功提示当关键字持久化成功。
候选测试仅临时绑定已安装 router 的同代码副本，正式调用仍是 C:\Users\Administrator\.agents\skills\xuanyuan-native-control\scripts\invoke.py；不新增永久入口。本节记录上述隔离副本的实测覆盖和明确限制，未验收的非空 TXT 导入语义、关键字持久化、有效 Pak 解密及业务下载不能据编译或模拟测试宣称通过；正式发布状态和每项真实窗口覆盖以正式 manifest 绑定证据为准。


## Native Control 1.1.22：派发后设置窗隐藏的结果

普通表单准入、snapshot、宿主/版本指纹与输入守卫保持原规则。一个动作在派发前已核验的独立表单，派发后不再出现在可观察表单名单中、但HWND仍存在时，仅在两次匹配的PID、路径、SHA256、进程创建时间、class/title、parent/owner/style与root元数据均确认其隐藏后，返回受限生命周期结果。前态hosted、WS_CHILD、标题截断、身份漂移或采样不稳定仍拒绝；只忽略WS_VISIBLE位变化。

结果中`target=null`、`targetClosed=false`、`targetLifecycle.state='hidden'`；真实销毁为`targetClosed=true`及`state='destroyed'`。`dispatch`/handler ACK与生命周期分别记录，`businessSaveVerified`保持false。需要编辑/下拉/页签值回读却无法取得控件时仍失败，不把窗口隐藏当作参数保存成功。

`continuation.requiresFreshObservation=true`与`candidateForms`只给下一步线索，不授予输入。候选可以包含隐藏的TfrmMain；须以其当前PID/HWND/class/title做新的window-observe，隐藏主窗需用该新观察再明确show。不得把结果中的主窗截图替换成target、消费隐藏结果回执自动续发动作或重发确定。超时/未知ACK仍查failure.json及现场，不自动重试。

本修复不支持新的GameCenter指纹，不启停引擎，也不证明业务配置已保存或原生防护实际生效。实际发布以正式manifest为准。


Native Control 1.1.23：GameCenter宿主类名兼容修复
继续使用原invoke.py及m2/engine的window-observe/window-action；不新增控制器或业务接口。宿主仅接受TfrmMain、TFrmMain两个精确类名，其他大小写及未知类仍拒绝。固定SHA、同根路径、PID/创建时间、完整父链、可见启用、观察回执、焦点和输入归属校验保留；观察后在两类名间变化仍使旧回执失效。
本轮为类名准入缺陷离线回归及同源发布，未操作业务GUI、重读QFunction、启用检测或启停引擎。主窗宿主关系、菜单重读与业务效果由原任务使用新观察继续验证，不因class修复宣称业务成功。1.1.22隐藏后置回执协议保持；旧m2-reload隔离根限制保持。


Native Control 1.1.24：原window-action新增minimize
仍使用原invoke.py，DBServer用adapter=engine。先对DBServer自身PID/HWND/完整EXE及SHA做新的window-observe，实际核对该窗口截图与hosting；随后以该回执和SHA提交window-action，action仅为{"kind":"minimize"}（可选原settleMs）。不可把GameCenter父窗回执或跨PID标题栏坐标当作DBServer凭据。
仅对可见、启用、未最小化、无模态阻挡且有完整标题栏、系统菜单和最小化框样式的已验证窗口派发一次WM_SYSCOMMAND/SC_MINIMIZE；发送目标是该窗口自身HWND，不能用宿主rootHwnd代替。固定指纹、同根、PID/创建时间、宿主与父链、新观察/原值及焦点/点位保护保留。原前台若就是待最小化的独立窗口则派发前拒绝，避免恢复前台与维持最小化冲突。
ACK只表示处理返回，必须核对实际IsIconic状态及窗口身份；恢复原前台和鼠标后再次核验仍最小化，readbackVerified=true才表示UI最小化回读通过。程序忽略命令、窗口消失/身份变化或恢复撤销最小化均失败，不自动重发。最小化后screenshot可为null；这不代表关闭，更不代表服务停止、落盘保存或业务重读。恢复窗口沿原show动作及新观察合同。
本轮只做离线Win32边界回归、冻结源及发布核验，没有操作现场DBServer、重读物品/QFunction、启用检测或启停组件。现场最小化、遮挡解除与业务效果由原任务继续验收。996仍暂停。
