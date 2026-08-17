# 捐献状态文件修复游戏验收

- 日期：2026-07-30
- 目标：验证平台预创建`玄渊数据\xy_donate\捐献状态.txt`后，沙城捐献不再出现`CREATEFILE`与`WRITECONFIGFILEITEM Save fail`。
- 候选处理：当前服只创建唯一父目录和0字节初始文件，未修改捐献核心、配置、NPC或QFunction。
- 用户结论：游戏内验证通过。
- 正式沉淀：成果包以`copy + preserve_existing=true`事务创建状态文件；运行时不再执行`ForceDirectories/CreateFile`。
- 数据保护：新服创建0字节文件，已有服逐字节保留现有状态文件，重复安装幂等，回滚恢复安装前文件。
