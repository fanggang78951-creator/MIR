# 当前发布入口：1.1.12

2026-10-18 Native Control 1.1.12：固定共享后继函数只读取证
仍为同一技能adapter=m2、command=m2-event-evidence和固定profile=custom-monster-summon-v1；最低版本1.1.12。
在原3个handler之外，仅补固定RVA0xFD1F30的512字节callee；VA由现场actualBase计算，不开放地址/长度参数。
在原有完整243条published表校验中记录该地址的全部匹配方法名，0/1/多均如实；0只表示本表内未找到。callee不是第四个DFM handler。
真实100端身份前后核验、跨页只读采集及REA/Ghidra实际callee指令/512字节回读通过；原三个片段832字节并集亦一致。
权威4份raw bins覆盖两段1344字节；17408字节标准静态DLL的其余15040字节.text为CC合成填充，仍只导出3个原handler。
未执行或LoadLibrary，不触发GUI/事件，不修改REA策略、正式端或GlobalVal；完整函数与片段外调用/分支未知，业务规则由调用窗口验证。
合同：C:\Users\Administrator\.agents\skills\xuanyuan-native-control\references\event-evidence.md
正式冻结来源：E:\XuanYuanDevPlatform\wzl编辑\evidence\20261015_native_control_tool\v1.1.12；旧窗口/游戏/业务验收不计为本轮新增验收。

# 当前发布入口：1.1.11

2026-10-18 Native Control 1.1.11：REA/Ghidra静态载体兼容修复
同一技能入口adapter=m2、command=m2-event-evidence；固定profile=custom-monster-summon-v1，事件命令最低版本1.1.11。
修正1.1.10非可执行PE被REA拒绝的问题：输出code-entry-snippets.analysis.dll，标准AMD64 PE32+ DLL，仅供静态分析，严禁执行或LoadLibrary。
REA 6.5.0 / Ghidra 12.1.4真实导入成功，三个事件入口指令读取15/49/34条；832字节回读与原始bin并集一致，载体offset已实读核验。
三个512字节bin仍为权威；导出名称为合成分析辅助，3264字节CC填充非原始指令；原PEoffset仍为null，完整函数及片段外调用未知。
本轮离线修复已有采集，不新增进程读取、不触发GUI或业务实验、不修改REA/客户端策略；采集目标白名单及只读后端保持原合同。
合同：C:\Users\Administrator\.agents\skills\xuanyuan-native-control\references\event-evidence.md
正式冻结来源：E:\XuanYuanDevPlatform\wzl编辑\evidence\20261015_native_control_tool\v1.1.11；旧窗口/游戏/业务验收不计为本轮新增验收。

# 当前发布入口：1.1.10

2026-10-18 Native Control 1.1.10：受限Delphi事件只读取证
同一技能入口新增adapter=m2、command=m2-event-evidence；固定profile=custom-monster-summon-v1。
唯一目标D:\Mirserver100\Mir200\M2Server.exe，现场PID/路径/原版SHA核验；禁止正式端与任意地址/长度参数。
仅被动读取已映射主模块固定DFM/VMT与三个处理函数入口片段，不改变保护、不注入、不触发GUI、不修改业务；GlobalVal.ini只观测。
合同：C:\Users\Administrator\.agents\skills\xuanyuan-native-control\references\event-evidence.md
输出为DFM→VMT→published方法表地址关系及最小原始代码片段，运行内存来源与原PE文件offset分开；不宣称派生开关或当前实例事件指针已证实。
正式冻结来源：E:\XuanYuanDevPlatform\wzl编辑\evidence\20261015_native_control_tool\v1.1.10；旧窗口/游戏/业务验收不计为本轮新增验收。

# 当前发布入口：1.1.9

2026-10-18 Native Control 1.1.9：原生窗口字段与菜单接口已发布
同一工具新增window-observe/window-action，支持原版M2/GameCenter/MakeGameLogin/WZL窗口的观察、控件设值、选项、标签页、按钮、菜单、关闭及自绘区域单次键鼠操作。
固定EXE：E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeControlTool\XuanYuanNativeControlTool.exe
统一调用：python -X utf8 "C:\Users\Administrator\.agents\skills\xuanyuan-native-control\scripts\invoke.py" --adapter m2|engine|launcher|editor --request 请求.json
完整合同与字段保存/重读/回读链：C:\Users\Administrator\.agents\skills\xuanyuan-native-control\references\window.md
inspect已增加hwnd；窗口请求绑定现场PID/完整路径/原版SHA256/精确窗口，以及120秒内观察回执SHA。每请求一个动作，未知弹窗和超时不自动确认或重发。
字段无需逐个加入engine-parameter；旧人数间隔合同保留。本次新增验收使用实验端独立怪物的名称X/Y及类型，实际原生保存、完整INI差分、怪物库重读ACK、GUI回读与精确恢复。
通用window-action可操作任务中明确授权的正式原生窗口；不会自动授予业务改值、启停、发布、资源覆盖等权限。旧高层命令限制不变，game接口继续只作用于原LabClient。
原始资源工具1.0.1未替换。正式冻结来源与本轮证据：E:\XuanYuanDevPlatform\wzl编辑\evidence\20261015_native_control_tool\v1.1.9

以下为历史分版本合同，具体能力以当前manifest和技能window.md为准。

# 登录器副本生成与隔离引擎调用

工具入口：`E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeControlTool\XuanYuanNativeControlTool.exe`。

收尾观察：共享固定入口后来变为匹配自身manifest的1.1.5，不是本页14验收产物；其冻结等待方法未含14的caption快照修正。未覆盖该后续版本。复现本页请从14 Release独立下载并核6F536E16…BF7440C，不因版本号更高继承M2/沙盒通过结论；统一合并另核来源与授权。

本页描述 **1.1.4** 合同，实际安装及下载版本以匹配manifest和EXE SHA为准。修正原生窗体caption快照并补齐[沙盒准备与交接](../tools/native-sandbox/README.md)；完整链见[客户端导出生成链](native-control-client-chain.md)。仅支持 `exportKind=custom-monsters`；真实原版导出、保存、生成与输入哈希绑定不代表在线客户端下发或游戏验收。下文1.2.0仍是未发布施工说明，固定EXE不提供`engine-start/engine-stop`。1.1.2/1.1.3作为历史证据保留，不能由旧成功覆盖后续失败。

系统前提：目标64位Windows需要Microsoft Visual C++ v14 x64运行库。单文件EXE不代表零系统依赖；先前“干净子环境”测试清理了PATH/PYTHONPATH，但宿主已有系统运行库，不能外推为全新Windows测试。禁网Windows沙盒曾实际报win32ui依赖的MFC DLL缺失；安装微软官方签名的v14 x64运行库后已能进入原版控制台。安装仅在来宾执行，未修改宿主。

官方运行库：https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist 。本地工具和本库不分发该安装包。

本工具复用同一项目的 `NativeEditor` 进程管理和原生控件操作，不修改资源编解码器，也不重新实现登录器生成算法。入口实现为 `src/wzl_blackbox/native_control.py`，隔离引擎适配为同包 `native_engine.py`，单文件入口为 `native_control_entry.py`。版本、二进制和源码指纹以工具目录 `tool.manifest.json` 为准。JSON输入、输出和诊断流固定UTF-8，不依赖Windows默认代码页。

## 1.0.0 历史支持范围

- `launcher-save`：完整复制登录器目录，将副本输出重定向到新任务目录，由原版执行“保存配置”，再回读。
- `launcher-build`：完成上述保存流程，再由原版生成登录器。核对文件夹选择树完整路径，等待打包进度及原版“配置成功”提示，退出副本后验证唯一 EXE 的 MZ/PE 结构与指纹。
- `inspect`：确认 PID 对应的完整程序路径，读取原生窗口、菜单、按钮及复选框状态。已在当前 GameCenter、M2 上实际验证。包含嵌入式子窗体的查找，不仅枚举顶层窗口；主窗口隐藏时仍只读识别并返回visible=false，不需要恢复或激活正式窗口。

没有引擎启动、停止、重读、菜单执行、设置保存或任意键鼠命令。菜单中出现“重新加载”只代表读到了该入口，不代表已经执行，也不证明它的游戏效果。

固定生成器：`D:\MirServer\登录器\MakeGameLogin.exe`，界面版本2026-09-27；SHA256为 `340C5D6B7436DC0F50D27C7844BE29A381C230B65C1112683D2059F2DCE9AD35`。其他二进制版本先停下验证，不猜控件。

## 调用

```powershell
& 'E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeControlTool\XuanYuanNativeControlTool.exe' capabilities
& 'E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeControlTool\XuanYuanNativeControlTool.exe' run --request 'D:\任务\request.json'
```

`run --request -` 从标准输入读取 UTF-8 JSON。成功退出0，失败退出1；标准输出为一个 JSON，诊断警告可能出现在标准错误。成功任务根目录保存 `receipt.json`，失败副本留在任务目录，不会回滚或覆盖原文件。

### 保存或生成

```json
{
  "schemaVersion": 1,
  "command": "launcher-build",
  "arguments": {
    "sourceDirectory": "D:\\MirServer\\登录器",
    "outputRoot": "D:\\codex临时工作区\\launcher-jobs\\job-001"
  },
  "policy": {
    "allowedWriteRoots": ["D:\\codex临时工作区\\launcher-jobs"]
  }
}
```

输出结构：`generator/`为隔离生成器；`artifacts/`为产物；`receipt.json`为核验收据。

`outputRoot`必须不存在，且不能位于原生成器、原配置输出目录或正式服务端/客户端根下。原SaveFilePath若非空必须为完全限定路径，不能将相对原输出路径按调用器目录错误解析。输入目录不能有重解析点；Config.ini中列出的素材路径若为绝对路径或包含父级跳转，会停止，要求先做完整、自包含的素材包，不静默丢掉素材。

副本Config.ini只重绑定SaveFilePath；副本GUI_Config.ini只重绑定ImageLibrary。保存的编码保持原INI编码，使用CRLF。PAK资源登记、密码和其它参数保留在本地副本，不在回执输出配置正文。

源目录全部文件前后SHA256必须相同；额外核对原输出目录顶层既有文件、与“补丁文件夹”对应的目标文件。该检查不是对整个客户端目录的全量监控，也不是操作系统级沙箱；不要将本工具视为可运行任意未验证生成器的通用沙箱。

### 引擎或M2只读识别

```json
{
  "schemaVersion": 1,
  "command": "inspect",
  "arguments": {
    "pid": 12345,
    "expectedExecutable": "D:\\MirServer\\Mir200\\M2Server.exe"
  }
}
```

PID必须用当前进程列表重新取得，不能复用说明中的12345或旧测试PID。控制台对应 `D:\MirServer\GameCenter.exe`。路径不一致会拒绝，防止PID复用误读。该操作不会启动目标进程、切换标签或打开菜单；不读取文本输入框内容和日志正文。

## 1.0.0 验证与边界

该版本回归覆盖原有108项与新增22项调用器测试。真实副本保存与生成通过，产物约44.6MB；此处仅证明当前原版及当前输入包的生成链，不证明新EXE已部署、资源完整读取或游戏正常。PE由pefile核验COFF、可选头、节表及原始节范围，不仅检查MZ/PE签名。

文件夹选择器显示末级名称而非完整路径，不能拿输入框文字与绝对路径直接比较。工具读取当前选中TreeView节点及全部父级，核对盘符与目标完整路径后才确认。生成成功只接受已验证的“提示”标题、完整固定文案结构、与源配置匹配的URL及唯一确定按钮；保存必须等待“提示信息”标题、完整正文“配置信息保存成功！！！”和该窗口的唯一确定按钮（当前控件ID为2），不能以短暂未出现弹窗当作保存结束。按钮ID按具体弹窗固定，不把所有“确定”都视为同一控件。未知覆盖、错误或其他对话框会停止，不连续回车。

需要未锁定的Windows交互桌面，会短暂使用自己的生成器窗口焦点；任务必须串行。只关闭本次副本PID，不关闭用户程序或引擎。原版可能写Windows自身的窗口位置/最近目录等用户级状态，本工具未提供注册表或全系统写入隔离；禁止把“副本测试”表述为系统级无副作用沙箱。

以上为1.0.0历史验证范围。1.1.0新增的严格副本能力见下节；正式服仍只读。

## 1.1.0 隔离测试服调用

用户授权日期：2026-10-15。扩展同一个NativeControlTool，不增加第二套控制器或后台守护程序。

仅接受`D:\codex临时工作区`内、无重解析点/硬链接的独立最小测试服。预检绑定本轮原版GameCenter、M2、DBServer和Mir.dat的准确SHA256；目录、双SQLite键、网络端口、脚本、插件均有检查。当前实验不是完整可登录服务器，也不是操作系统沙箱。

新增command：
- `engine-preflight`：只读检查副本配置，返回`configurationOnly=true`。不把配置中的回环IP当成运行时隔离证据。
- `engine-controller-start` / `engine-controller-stop`：只启动/关闭GameCenter控制器本身，不点击整套服务启动停止。要求先停副本组件。控制器启动会再生成组件配置，因此对已知5份配置拍快照、恢复并复预检，返回变化清单。
- `m2-start` / `m2-stop`：只操作该副本M2，拒绝重复启动；启动需原生初始化完成及实际IPv4监听仅`127.0.0.1:25000`。正常停止核对退出弹窗并等进程退出，不强杀；失败启动只清理本次Popen创建的副本。
- `m2-reload`：target为`qfunction`、`qmanage`、`items`、`skills`、`monsters`、`npcs`、`parameters`。前六项核对本次日志增量中的原版完成文案；日志截断、错误或未知弹窗不认定成功。参数重读只确认原生派发与下述已支持参数的GUI回读，不证明其它参数或游戏效果。
- `engine-parameter`：当前唯一允许的parameter为`console-user-count-interval`，即“参数设置→环境设置→控制台显示人数时间(秒)”。`value`和`expectedValue`均为1..3600整数秒；对应`!Setup.txt/[Setup]/ConsoleShowUserCountTime`毫秒值。先备份，再由原版GUI修改、保存、单键差分、重开回读；其他参数一律拒绝。

所有操作arguments含`labRoot`；除两个start和preflight外另传实时`pid`。写操作必须带`policy.allowedWriteRoots`。PID、完整EXE路径及SHA在操作前复核；正式根目录即使出现在allowedWriteRoots也会拒绝。引擎写调用通过会话级命名互斥串行；界面已被弹窗阻塞时不再重复打开设置页。

```json
{
  "schemaVersion": 1,
  "command": "engine-parameter",
  "arguments": {
    "labRoot": "D:\\codex临时工作区\\native-control-20261015\\engine-lab",
    "pid": 12345,
    "parameter": "console-user-count-interval",
    "expectedValue": 600,
    "value": 601
  },
  "policy": {"allowedWriteRoots": ["D:\\codex临时工作区\\native-control-20261015"]}
}
```

此PID只是示例。不得复用测试时旧PID。当前固定最小样本使用M2网关25000、DB连接26000、IDS连接25600、消息24900、日志30000；这些不是正式服端口。源码`native_engine.py`为唯一校验合同，不能拿本样本当任意服务端的通用配置迁移器。

### 已确认的限制

1.1.0已测旧DBServer SHA256 `86868707C18D36D044109BF913535F37BB85B40318F04F5510089E4A8A708AE7` 即使配置`ServerAddr/GateAddr=127.0.0.1`，实际仍监听`0.0.0.0`；该副本已关闭。1.2.0已在禁网沙盒补测当前版本，其指纹和结果见后节；宿主最小副本仍不开放整套服务管理。

2026-10-15用户授权启用Windows Sandbox并自行重启后，已回读Enabled、HypervisorPresent=true且无待重启标记。禁用网络的沙盒探针实测无非回环地址、无默认路由、输入映射实际只读，输出只映射独立空目录。隔离探针和后续整套启停证据分别保存；未修改宿主防火墙或操作正式服。

M2存在`TfrmGeneralConfig`等小写类名。只认`TFrm`会漏报已经打开的模态设置窗；1.1.0同时读取可见顶层窗口及大小写不同的Delphi窗体。原版TabControl文字读取在此版本曾触发comctl32异常，不采用该路线。

多按钮确认不能仅依赖发送空格或BM_CLICK后窗口消失；先核对完整文案、按钮ID6/7、精确前台HWND，再发送BM_CLICK并验证进程结束。微软说明非活动对话框的BM_CLICK可能失败：
https://learn.microsoft.com/en-us/windows/win32/controls/bm-click

监听核验使用Windows实际PID/TCP表，不只读取INI：
https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcptable_owner_pid

翎风官网更新日志只用于核对版本和能力线索，不替代当前副本实测：
https://lfm2.com/rizhi.html

本轮未部署正式服、未启动客户端或完成游戏验收。GUI回读通过不外推为全部参数、全部引擎版本或完整商业服运行通过。

## 1.1.1 主窗识别修正

同一SHA的原版控制台在新沙盒中实际返回主窗类名`TfrmMain`。主窗选择、隐藏主窗枚举、弹窗排除均按不区分大小写处理`TFrmMain`；唯一主窗和完整PID/路径/SHA校验保持不变，不容许多个大小写不同的主窗蒙混通过。新增2项测试并扩充原有2项测试，单测总数166；实际调用与当前发布状态以tool.manifest.json及对应版本报告为准。

## 1.1.2 登录器启动修复与直接调用

生成器主窗实际类名为`TfrmMain`。1.1.1只对引擎主窗修正大小写，登录器继承的初始化仍写死`TFrmMain`，并只等visible 15秒；本机复现约18秒才建窗、20.969秒才可见且可用。故早期`inspect`返回`windows=[]`不等于原版无法识别。

1.1.2在原有适配器内使用`class_name_re=(?i)^TFrmMain$`，仍限定本次创建的PID；分别有界等待visible、enabled，各最多60秒，再执行原有控件操作。不会接管用户窗口、无限重试或修改原版二进制。`inspect`仍是当次只读快照，不会自行启动或唤醒目标。

本机直接使用本页顶部固定EXE，先读同目录manifest核对版本及SHA；不必让用户手动生成。调用`launcher-save`或`launcher-build`沿用上面的JSON，不复制旧outputRoot；工具需要交互桌面，任务串行。每状态60秒是上限，不是固定睡眠；调用端应给完整保存/生成流程留至少240秒，不要把外层20秒限时误当生成器失败。

本次新EXE的真实副本保存、生成及PE核验通过；报告为`evidence/20261015_native_control_tool/v1.1.2`。源及受保护客户端文件未变。新候选全套167项测试（1项可选Provider EXE测试跳过）和当前施工源码207项回归通过，不能冒称本EXE重新做过旧版31项引擎启停实操。引擎/权限模块与1.1.1完全相同，本轮只读识别和拒绝用例，不启动或停止引擎。

发布源码是已发布1.1.1冻结模块加权威源码现有启动修正的最小回移，工具版本升1.1.2；E盘当前1.2.0施工源码保留，不回退覆盖。每个EXE以manifest绑定的冻结模块为准；不拿资源工具共用模块的另一个版本号拼成同一次构建。

私有Release：`verified-20261016-control-1.1.2-resource-1.0.1`；新窗口先读仓库`currentVerifiedIncrement`，下载EXE和manifest并核对SHA，再传上述JSON即可。GitHub权限不赋予远控权限，仍须在目标Windows本机执行。

## 1.2.0 禁网沙盒整套启停（未发布候选）

仍使用同一个工具和`native_engine.py`。`engine-start`、`engine-stop`仅允许来宾固定目录`C:\NativeLab`或`C:\NativeDirectoryLab`，每次实时检查实际用户名`WDAGUtilityAccount`、无非回环IPv4/IPv6地址、无默认路由。宿主的D盘最小副本和正式服均拒绝这两个命令；`allowedWriteRoots`不能扩大该范围。

预检复用原配置、SQLite、脚本、插件、重解析点和硬链接检查。沙盒profile绑定当前GameCenter、M2、DBServer、Mir.dat及五个其它组件的9个文件SHA；D盘profile继续绑定原先经过验证的最小副本，不混用不同DBServer指纹。`LoginSrv\IDDB`必须存在且配置精确指向该私有目录。

- `engine-start`：要求控制台和七组件均未运行；打开原版控制台，选择DBServer、M2、LoginGate、LoginSrv、LogServer、RunGate1、SelGate1，确认原版启动问题。七个组件各有唯一PID，M2实际监听符合副本配置，且本次日志包含初始化成功、IDS连接成功和DB连接成功，才返回成功及实际监听表。
- `engine-stop`：必须传启动回执中的实时控制台PID；原版正文为`是否确认停止游戏服务器?`，并非M2单独退出的文案。所有组件正常退出后，再确认`是否确认关闭控制台 ?`并等待控制台实际退出。正常停止不强杀。
- 沙盒按钮只向核对过的具体HWND派发`BM_CLICK`；确认框仍需全文、类名、按钮ID6/7和PID一致，并要求`GetGUIThreadInfo`返回的线程活动窗口正是该确认框。没有取消活动窗口检查，也不向全局键盘发送确认键。宿主旧操作仍保持原前台焦点合同。

请求在来宾执行，调用方式不变：

```json
{"schemaVersion":1,"command":"engine-start","arguments":{"labRoot":"C:\\NativeLab"},"policy":{"allowedWriteRoots":["C:\\NativeLab"]}}
```

```json
{"schemaVersion":1,"command":"engine-stop","arguments":{"labRoot":"C:\\NativeLab","pid":12345},"policy":{"allowedWriteRoots":["C:\\NativeLab"]}}
```

`12345`必须替换为当次启动结果的PID。宿主通过微软原生`wsb list --raw`获取当次沙盒ID、`wsb exec --id ... --run-as ExistingLogin --command ...`调用只读映射中的工具。WSB CLI不转发命令标准输出，应用JSON应重定向至独立输出映射；`wsb stop --id ... --raw`只关闭已确认归属本任务的来宾，不操作宿主或其它沙盒。来宾需要官方VC v14 x64运行库；原版组件和最小数据须由用户合法提供，本工具不分发它们。

当前验证数量、EXE指纹与来源以发布目录`tool.manifest.json`和`evidence/20261015_native_control_tool/v1.2.0`为准。旧候选的176项/35项记录不代表后续源码或本次完整端已经验证。

当前DBServer SHA256 `06DA830E181A7DFDD913A4D322422AD01C755C8A105CA69AE08A7716C25DC6BE`在该沙盒实测仍监听`0.0.0.0:25100/26000`；其它网关也有宽监听。因此禁网来宾是本功能必要边界，不能把改成高位端口当作网络隔离。

种子打包必须保留空目录。此前丢失`LoginSrv\IDDB`造成原版日志`unable to open database file`，补齐目录后七组件启动通过；不是修改数据库格式或二进制。该最小服只有一张地图，无玩家和业务NPC，仍有缺城堡等数据提示；初始化与工具调用不等于商业服、游戏登录或全部参数验收。任意参数、任意菜单、正式服写入没有开放。

### 完整测试端与原生目录配置

`C:\NativeDirectoryLab`使用用户完整测试端的独立副本。先由原版控制台执行“自动设置服务器目录”，核对自身目录及成功提示，正常关闭并重开；不要先猜测整套配置格式。已验证该按钮改6个文件，其余5347个原文件不变，SQLite和业务脚本未被按钮修改。

该profile保留业务脚本和原生端口；只有在实际禁网WDAG内才接受原生的`0.0.0.0`监听字段（含MsgSrvAddr）。复制后的外部插件禁用，DLL/Lua、外部活动数据库、重解析点和硬链接仍拒绝。AccessFileName只在UseSqliteDB=1未选用时保留；旧G盘BoxsFile/SortDir/ChatDir仅在该盘不存在时作为明确遗留项返回`retainedLegacyPaths`，不自动全局替换。

原版Config.ini可能是UTF-8 BOM加GB18030正文；读取时先拆BOM再识别正文，不为方便解析改写原文件。控制台主窗先显示无目录的“翎风引擎控制台”，稍后才更新目录；只等待这个已实测的初始标题，错误的已初始化目录仍拒绝。停止时必须等待控制台恢复启动按钮，再核对并正常关闭。

### 新的本地Codex窗口

新窗口不需要靠通用截图接口识别原生窗口，直接从本仓库私有Release下载两个自有工具EXE和匹配manifest，核对SHA256后用本页及`native-resource-tool.md`的JSON命令。资源工具的能力命令是`meta capabilities`，控制工具是`capabilities`，两者不同。

需要Windows本机执行权限、未锁定交互桌面、VC v14 x64运行库，以及指纹匹配的用户合法原版程序。GitHub访问本身不赋予电脑操作权限，也不包含原版引擎、数据库、资源包或PAK密码。此机器可复用本任务已配置恢复包；换电脑须自行准备对应原版和隔离副本。不能复用历史PID或沙盒ID。

整套引擎请求改用`labRoot=C:\NativeDirectoryLab`、`allowedWriteRoots=[C:\NativeDirectoryLab]`，在来宾中执行；宿主资源/登录器任务应串行，输出目录必须尚不存在。调用前读取当前manifest，不从旧Release拼接新源码。没有已验证映射的参数和菜单不可借本接口执行；正式服仍只读，部署另需用户具体授权。

官方参考：
https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getguithreadinfo
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow

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
