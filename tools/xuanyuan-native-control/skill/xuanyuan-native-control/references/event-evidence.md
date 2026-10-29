# M2 固定 Delphi 事件只读证据

用于追查“自定义怪物召唤”控件的 DFM 事件绑定、VMT/published table 地址关系、handler 入口字节及一个固定共享后继 callee 的入口片段。统一入口为 `invoke.py --adapter m2`，后端仍为 Native Control；不新增常驻服务、后台或独立 EXE。

## 版本和目标

- Native Control 最低版本为 **1.1.12**，固定 EXE 的同目录 manifest 必须声明 `m2-event-evidence`，版本、工具身份与 EXE SHA256 每次核验。
- 只允许 `adapter=m2`；`game`、`engine`、`launcher`、`editor`、`resource` 均拒绝该命令。
- 唯一进程路径：`D:\Mirserver100\Mir200\M2Server.exe`。
- 唯一原版 SHA256：`1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A`。
- 唯一 profile：`custom-monster-summon-v1`。PID 每次现场确认，历史 PID 不能直接复用。

旧版返回 `event-unavailable` 时，需要部署已核验的 1.1.12+；manifest 未声明命令返回 `manifest-commands`。1.1.11 缺少本合同的固定共享后继证据，1.1.10 的旧载体不符合当前 REA/GhidraP0 的目标角色要求，均不能自动回退使用。不能绕开统一入口直接调用候选 EXE。旧版普通 M2 命令及能力查询保留原有门槛，游戏 1.1.8 和原生窗口 1.1.9 的门槛保持不变。

## 请求

先查询 `--adapter m2 --capabilities`，再准备 UTF-8 JSON。共享后继属于后端固定 profile 的读取范围，请求 JSON 和 profile 保持不变，不增加地址或长度参数。以下 PID 为占位示例，必须替换为当前目标 PID；`outputRoot` 使用本轮独立的证据目录，`policy.allowedWriteRoots` 仅允许本轮输出位置。

```json
{
  "schemaVersion": 1,
  "command": "m2-event-evidence",
  "arguments": {
    "pid": 4312,
    "expectedExecutable": "D:\\Mirserver100\\Mir200\\M2Server.exe",
    "expectedSha256": "1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A",
    "profile": "custom-monster-summon-v1",
    "outputRoot": "D:\\任务目录\\event-evidence-run-1"
  },
  "policy": {
    "allowedWriteRoots": ["D:\\任务目录"]
  }
}
```

顶层只接受上面四个字段；`arguments` 和 `policy` 也只接受示例列出的字段。`schemaVersion` 必须为整数 1，`pid` 为正整数；路径及哈希必须匹配固定原版，`outputRoot` 和允许写入根为绝对路径。不能附加任意地址、长度、模块、函数名、注入、调试或写内存参数。输出是否位于允许根及来源保护由后端继续核验。

```powershell
python -X utf8 'C:\Users\Administrator\.agents\skills\xuanyuan-native-control\scripts\invoke.py' --adapter m2 --capabilities
python -X utf8 'C:\Users\Administrator\.agents\skills\xuanyuan-native-control\scripts\invoke.py' --adapter m2 --request 'D:\任务目录\event-request.json'
```

调用前核对目标 PID、完整路径和 SHA256；按后端结果检查本轮输出及回执。失败或没有回执时先核对状态，不自动重发。会话级互斥仍覆盖整个后端生命周期。该命令不需要先做 GUI 观察，也不会打开、关闭、切换或触发 M2 窗口。

## 固定读取边界

只读当前目标**已加载主模块**中的指定证据：固定 DFM **94,135 bytes**、VMT/published table 元数据预算 **128 KiB**、下列三个唯一 handler 入口各 **512 bytes**，以及一个固定共享后继 callee 的 **512 bytes** 入口片段。

| 唯一 handler | 绑定关系 |
|---|---|
| `seCallMonstersRateChange` | 自定义召唤比率控件 |
| `edtCallMonster1Change` | 四组怪物名称控件共享；`Tag=0..3` |
| `seCallMonsterNum1Change` | 四组怪物数量控件共享；`Tag=0..3` |

共享后继固定 RVA 为 `0xFD1F30`。每次采集必须重新核验现场已加载主模块的 `actualBase`，以 `actualBase + 0xFD1F30` 确定本次 VA，不能直接复用历史绝对地址。它是独立 callee，**不是第四个 DFM 事件或新增 OnChange 绑定**，不接受调用方指定其他 RVA。

JSON 顶层 `sharedSuccessor` 记录该固定片段的角色、RVA、VA、长度、原始文件名、SHA256、来源及内存页证据；`originalFileOffset` 为 null，`carrierFileOffset` 只表示载体中的文件偏移。原始文件固定为 `fixed-shared-successor.entry.bin`。

`relationship.sharedSuccessorPublishedMethods` 记录 `calleeRva`、`tableFullyValidated:true`、`matchCount` 和全部 `matches`；每项匹配保留 `name`、`methodIndex` 及原有 `record` 证明。必须完整校验既定 published table，并收集所有同址匹配，不只取第一项。结果允许为 0、1 或多项：0 仅说明该已校验表内未找到同址 published 记录，不能说明 callee 不存在；1 或多项也不能自动把名称解释成 DFM 事件或业务语义。

不注入、不写进程内存、不改变内存保护、不读取任意地址、不启用调试、不触发 GUI、事件或 handler，不刷怪、不进行业务改值。`GlobalVal.ini` 只作为磁盘观测来源，不保存或重写。输出文件写入本轮证据目录，不能把“只读目标进程”理解为完全不落盘。

## 证据解释

JSON 保留地址关系、各字段的来源、原版指纹及原始字节片段。阅读时区分：磁盘原版来源、已加载模块读回、DFM 绑定名称、VMT/published table 解析、handler 入口片段，以及独立共享后继片段和同址 published 匹配。原始字节是后续独立 REA 分析的输入；本命令不替代反编译或业务实验。

输出包括 `event-evidence.json`、统一 CLI 的 `receipt.json`、三个 handler 的 `*.entry.bin` 和 `fixed-shared-successor.entry.bin` 共四份原始片段，以及 `code-entry-snippets.analysis.dll`。四份原始片段各为 512 bytes，始终是权威字节来源；载体保留本次实际 ImageBase 与片段 RVA。三个 handler 有重叠，其覆盖并集为 832 bytes（RVA `0xFCFC50` 起、长度 `0x340`）；共享后继另覆盖 512 bytes（RVA `0xFD1F30` 起、长度 `0x200`）。两段覆盖共 **1,344 bytes**，不能把四份片段相加当成 2048 bytes 的独立代码。`.text` 内其余 **15,040 bytes** 为人工 `0xCC` 填充，不能当成原进程代码。载体文件偏移和原 PE 文件偏移分别记录；本 profile 的原 PE 文件偏移为 null。

载体为 **17,408 bytes** 的标准 AMD64 PE32+ DLL，仍有两节：`.text` 从 RVA `0xFCF000` 起，扩大为 **16,384 bytes**；`.edata` 位于 RVA `0xFD3000`。包含 `IMAGE_FILE_EXECUTABLE_IMAGE | IMAGE_FILE_LARGE_ADDRESS_AWARE | IMAGE_FILE_DLL` 标记、`AddressOfEntryPoint=0`、Subsystem 2，无 imports 和 TLS。三个具名导出继续映射到上述真实 handler RVA，名称来自已核对的 published method 元数据；共享后继不增加 synthetic export。这些导出是载体的分析辅助信息，不能宣称原 PE 含有相同导出或调试符号。DLL 属于标准可加载格式，入口为 0 或无 imports 不代表物理不可加载或不可运行。**本工作流仅作静态分析，绝不调用 `LoadLibrary`、执行载体或调用导出，不修改 REA 或客户端安全策略。**

`.edata` 是合成的载体元数据，不能当成原 PE 事实。

新增共享后继的验收须由 REA 实际打开本轮 DLL，再读取 RVA `0xFD1F30` 的指令，核对原始字节、地址映射及采集覆盖。原三个 handler 若字节与映射已核验未变，可沿用已有独立 REA 指令证据，不能假称本轮已重测；旧版载体的打开结果不能替代新增共享后继的验收。文件生成、SHA256、PE 解析或导出表核验不能代替 REA 实际导入验收，文档中的格式说明也不代表已经验收通过。原始片段齐全且来源可追溯时，可离线重新封装载体，无需重新触发业务实验；不能合成未采集的 callee 字节来补足证据。

DFM 与 published table 结构可以支持绑定及地址的证据链；不得据此宣称已取得当前实例 `OnChange` 的运行指针、完整函数，或已确证 `EnabledCallMonster` 的派生规则。证据采集成功也不等于 M2 业务行为或游戏验收通过。

512 bytes 始终只是入口片段。函数越出采集覆盖时，其完整边界和未采集指令均为未知；覆盖外的调用目标、全局数据、原程序导入及其行为均为未知。跨片段的调用或分支关系仍须用实际指令和地址独立核验，不能由片段并置、published 名称或导出表自动证明，也不能据此自动证明 `EnabledCallMonster` 派生规则。载体自身没有 imports，不能推断原程序没有外部调用。REA 在容器内识别出的函数范围也不能单独证明原程序完整函数已被采集。
