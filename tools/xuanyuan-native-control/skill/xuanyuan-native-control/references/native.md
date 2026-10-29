# M2、GameCenter 与登录器适配器

后端固定入口：`E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeControlTool\XuanYuanNativeControlTool.exe`。版本与来源以同目录 `tool.manifest.json` 为准。`native_control.py` 共享施工源或旧文档版本不是已发布 EXE 的能力依据。

先读 `E:\XuanYuanDevPlatform\接口\登录器副本生成与引擎只读调用接口.txt`；按具体动作再读 `E:\XuanYuanDevPlatform\wzl编辑\docs\native-control-tool.md`。文档含历史与未发布节，只使用实时能力查询明确列出的命令。

字段编辑、下拉选项、原生保存按钮和菜单重读用 1.1.9 的 `window-observe` / `window-action`，见 [window.md](window.md)。它们按现场观察到的控件操作，可完成自定义怪物编辑链；不依赖 `engine-parameter` 逐字段白名单。以下旧命令继续沿用各自的原合同和范围，不把旧命令的能力限制套到通用窗口接口。

## 请求

通用外形为 `{"schemaVersion":1,"command":"...","arguments":{},"policy":{"allowedWriteRoots":[]}}`。

只读识别用 `adapter=m2` 或 `engine`：

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

`12345` 必须现场枚举替换；控制台路径为相应服务端根的 `GameCenter.exe`。该命令只读进程路径、窗口、菜单和支持控件，不主动激活窗口。

现场列出候选进程：

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'M2Server.exe','GameCenter.exe' } | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath
```

若同时存在正式与实验根，根据用户明确的目标根选择。请求只有“当前M2”且上下文无法区分时，先只读检查候选身份并说明歧义，不把示例的正式路径视为默认修改目标。只有唯一目标且路径已确认才提交后续操作。

`adapter=m2` 还允许传给原工具的 `m2-start`、`m2-stop`、`m2-reload`、`engine-parameter`、`m2-client-build`；`adapter=engine` 允许 `engine-preflight`、`engine-controller-start`、`engine-controller-stop`。列出路由不意味着这些命令可以作用于正式端。其原请求、准确 labRoot、特例生产授权及副本门禁全部保留。

`adapter=launcher` 使用 `launcher-save` 或 `launcher-build`，参数包括 `sourceDirectory` 和尚不存在的 `outputRoot`，写根通过 `policy.allowedWriteRoots` 指定。原生成器检查、源文件保护和 PE 回读继续由原工具完成。生成命令预算至少240秒；避免外层工具短超时后自行重试。

## 恢复与证据

原后端返回 `{schemaVersion,version,ok,command,data}`，技能路由器保存在 `backendResponse` 中。data 含 outputRoot 时原工具写 `receipt.json`。有界菜单操作应核实实际返回；超时/缺失回执时先检查当前窗口及文件，不重发。

窗口接口新增的字段编辑、保存、菜单与回读证据按具体目标单列。对未修改的旧启停、参数预设、导出模块仅报告适当回归；历史验收不外推到新增业务字段，也不以旧人数间隔项目充当新字段验收。
