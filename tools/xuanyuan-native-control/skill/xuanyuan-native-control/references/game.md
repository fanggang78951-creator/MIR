# 游戏窗口适配器

通过统一入口 `--adapter game` 调用。请求、stdout、文件均为 UTF-8。

## 1. 现场识别

```json
{"schemaVersion":1,"command":"game-inspect","arguments":{}}
```

读取 `backendResponse.data.targets`。选择唯一可见、启用、非最小化、标题为当前人物的游戏主窗；不能把启动器窗或同名其他人物窗当目标。若多个人物窗无法唯一判断，询问要操作的角色。

初始适配器绑定路径 `D:\Mirserver100\LabClient\LFM2-100-LAB.exe` 和 SHA256 `C47FF89016182E8E48E5CB85F4FF60571AC60AB5E16437F6B37C706C95477503`。这是已验证的实验客户端，不可传任意可执行文件。

## 2. 读取当前画面

用现场返回的 pid、整数 hwnd、class 和 title 填请求。示例中的整数需要全部替换：

```json
{
  "schemaVersion":1,
  "command":"game-observe",
  "arguments":{
    "pid":12345,
    "hwnd":123456,
    "expectedExecutable":"D:\\Mirserver100\\LabClient\\LFM2-100-LAB.exe",
    "expectedSha256":"C47FF89016182E8E48E5CB85F4FF60571AC60AB5E16437F6B37C706C95477503",
    "expectedTitle":"01区 - 测试",
    "expectedClass":"TfrmMain",
    "outputRoot":"D:\\codex临时工作区\\游戏任务\\observe-001"
  },
  "policy":{"allowedWriteRoots":["D:\\codex临时工作区\\游戏任务"]}
}
```

每个 outputRoot 必须尚不存在。它保存 `capture.png`、`observation.json` 和后端 `receipt.json`。必须实际查看截图再选择动作；窗口边框不是客户区。截图像素点 `(sx,sy)` 换成请求客户区点：`x=sx-(target.clientOrigin[0]-target.rect[0])`，`y=sy-(target.clientOrigin[1]-target.rect[1])`。clientOrigin 是 ClientToScreen(0,0) 实时屏幕坐标，不可复用以前的边框偏移。适配器在同一线程统一 per-monitor DPI 坐标，退出时恢复原线程DPI上下文。

观察会短暂前置游戏并使用桌面像素截图。PrintWindow 在该客户端会返回白色客户区，不能用其成功返回值判断画面有效。已识别模态窗、中心/动作点遮挡、身份/尺寸/焦点变化或恢复失败会报错。截图其他位置仍可能局部遮挡；查看图片发现遮挡就重新观察。单次检查与真实输入之间仍可能受到用户桌面操作影响。

本客户端前置后会显示自己的 `SoPY_Status` 状态条；仅当它禁用、带 NOACTIVATE 标志且完全位于游戏窗口之外时记入 `target.nonBlockingWindows`，不视为阻塞。与游戏窗口有任何像素交叠或其他条件不符时仍拒绝。

同进程 `TApplication` 的严格0宽0高基础窗口也仅记录为 nonBlockingWindows；有面积的TApplication继续阻塞，不能按类名整体放行。

## 3. 单个动作

在观察后120秒内使用 `game-input`。保留上述身份字段，改为新的 outputRoot，并增加：

```json
{
  "observationReceipt":"D:\\codex临时工作区\\游戏任务\\observe-001\\observation.json",
  "observationSha256":"上一文件实时Get-FileHash得到的64位SHA256",
  "action":{"kind":"key","key":"F9","holdMs":60,"settleMs":700}
}
```

此对象是增补到 `arguments` 的字段，不是完整请求。引用 `observation.json`，不要引用外层 `receipt.json`。调用前计算该文件SHA256，不修改回执正文或截图来绕过时间、进程创建时间和窗口几何校验。

可选动作：

| kind | 字段 | 说明 |
|---|---|---|
| `hover` | `x,y,settleMs` | 客户区内移动鼠标，读取悬浮提示 |
| `click` | `x,y,button,holdMs,settleMs` | button为left/right，单次按下/释放 |
| `key` | `key,holdMs,settleMs` | F1..F12、ESC、TAB、B、I之一 |

holdMs范围0..1000，settleMs范围0..3000。初版不支持文本、粘贴、组合键、无限按住、任意按键脚本或进程注入。F9在本任务客户端为背包快捷键；其他键含义需看当前客户端设置。

每次操作前再次检查目标，输入后保存新截图并恢复鼠标和原前台。点击/按键的 `inputSent=true`表示系统已接受输入事件；hover表示已读回鼠标位置。游戏是否处理、任务是否完成仍须看图。`visualVerificationRequired=true`表示还必须确认背包是否打开、人物是否跑动或目标是否死亡。下一动作应基于刚返回的新 `observation.json` 和新截图，不能继续沿用旧战斗/移动坐标。120秒只是过期门禁，画面变化后即使未超时也应重新观察；当前回执没有强制单次消费标记。

出现 `failure.json` 时读取恢复状态与输入阶段。输入后截图失败也可能已改变游戏状态；先重新观察，禁止自动重发。用户按住物理鼠标/修饰键时应等其释放后重新观察，不清除用户输入状态。

## 4. 动作选择

- 背包：先看图确定当前开关状态，再单次F9；验证标题/格子出现或消失。
- 跑动：从截图找可行走空地，单次右键；场景滚动后重新读取地图坐标/新画面。不要用原屏幕坐标推定返回原地。
- 战斗：先确认怪物名称和可见血条，单次左键锁定；角色可能自动连续攻击。观察掉血、死亡模型和奖励；用户游戏内确认也作为验收记录。
- 不因路线困难改用GM命令、刷怪、无敌、地图移动或服务端配置修改。用户已指出怪在当前地图时直接在当前画面定位。

已知原先中文聊天粘贴出现过乱码并进入管理员模式，初版不提供该能力。本技能不修复/开启角色模式、不修改服务端状态。
