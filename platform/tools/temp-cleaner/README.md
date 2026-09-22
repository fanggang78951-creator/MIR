# 玄渊平台临时文件安全清理器

本工具只处理 `D:\XuanYuanDevPlatform` 内经规则识别、且由用户明确勾选的候选项。

安全约定：

- 默认只勾选达到保留天数的 Python/测试缓存。
- `build`、`tmp` 和失败事务残留只列出，永不自动勾选。
- 素材库、成果包、表格、证据、备份、正式 EXE、客户端补丁等目录硬保护。
- 不提供永久删除；确认清理后移动到 `backups\cleanup_quarantine`。
- 每次隔离生成 `receipt.json`，可用“按收据恢复”逐路径恢复。
- 扫描后内容发生变化、路径越界、发现链接/重解析点或原位置存在同名内容时阻止。

双击 `D:\XuanYuanDevPlatform\bin\XuanYuanTempCleaner.exe` 使用图形界面。

源码命令行：

```powershell
python D:\XuanYuanDevPlatform\tools\temp-cleaner\run_cleaner.py scan --root D:\XuanYuanDevPlatform --days 14 --output D:\XuanYuanDevPlatform\evidence\TempCleaner_Scan.json
```

扫描只在明确指定 `--output` 时写一份报告，图形界面普通扫描只保存在内存中，避免制造更多临时文件。

