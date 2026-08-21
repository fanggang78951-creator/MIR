# 当前交班｜平台应用窗口

- 状态：任务已下达，等待平台应用窗口执行
- 当前任务：十大陆材料系统的平台对象、来源怪物、掉率和关联装备接续落地
- 当前执行单：`outputs/elden_ring_10_continent_material_system_20260821/06_当前任务单_平台应用窗口_材料系统接续落地.md`
- 基础设计单：`outputs/elden_ring_10_continent_material_system_20260821/04_当前任务单_平台应用窗口_材料怪物装备.md`
- 分支：`codex/elden-ring-c01-v1-20260820`
- 上游输入：`outputs/elden_ring_10_continent_material_system_20260821/phase1_script/`
- 并发状态：用户已报告脚本窗口两项任务完成，但截至任务下达时统一交班和材料映射尚未提交到当前分支
- 执行规则：先同步并复用脚本成果；上游映射未出现时只做平台与数据库只读预检，不另分配一套68材料Idx
- 本轮边界：不重做NPC/任务/称号脚本，不启动553只怪物和十大陆全部装备的完整数值重做
- 最终交给脚本窗口：`outputs/elden_ring_10_continent_material_system_20260821/platform_app/07_交给脚本窗口_平台对象映射.json`
- 下一步：平台窗口提交成果SHA后，由主设计核验真实修改、编号冲突和阻断对象
