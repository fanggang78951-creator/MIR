# 聆风统一原生控制工具 1.1.24

本目录保存已正式安装的 1.1.24 原版 EXE、对应冻结源码、离线测试和统一调用技能。996 分支及 1.1.25 候选不在本次发布中。

入口见 `skill/xuanyuan-native-control/SKILL.md`。路由器沿用本机固定安装路径和目标指纹，下载到其他电脑不代表已经安装或适配。资源适配器依赖单独发布的 Native Resource 工具，本目录不包含它。

本版新增目标窗口 minimize 动作及动作后、焦点恢复后的状态回读；保留目标身份、宿主和观察回执校验。离线测试不代表业务保存或游戏验收。

## 离线验证

在 Windows 中运行 `python -m pip install -r requirements-test.txt` 安装测试依赖后，从本目录运行：

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m pytest tests -q
```

原正式验证记录：820 tests、162 subtests。`verification/github-sync-verification.json` 记录本次同步核验。

正式 EXE SHA256：`E2C53964430D3D005C1E37EAB15D65EC05BE9440DF74830A2D122264157C9EA2`。

manifest 和原验证文件保留正式发布时的本机来源路径，GitHub 文件映射为本目录的 src、dist、skill、docs。没有自动安装、启停或业务写入步骤。
