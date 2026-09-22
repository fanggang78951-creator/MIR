# 攻速突破平台沉淀设计

日期：2026-08-30  
状态：当前服已游戏验收；平台候选实现，跨服待验收

## 目标

把当前服已验收的攻速阈值核心沉淀为独立非常驻包，并把“攻速突破”加入做装备共享母表、兼容用户表和正式脚本属性注册表。当前服只作金样本和冻结预检目标，本轮不安装、不修改。

## 包与路由

- 包ID：`xy.optional.attack-speed-breakthrough`
- 路由：`attack-speed-breakthrough`
- 状态：`candidate/optional`
- 配置表：`所需材料表格汇总/43_攻速突破.xlsx`
- 服务端核心：`Mir200/Envir/QuestDiary/玄渊攻速突破/全身攻速阈值核心.txt`
- 共享文件：`CustomItemPropertyTextVarList.txt` 第40行、`QFunction-0.txt` 三个事件挂钩和统一重算入口

## 数值合同

- `突破生效=min(max(全身突破,0),30)`。
- `个人阈值=min(20+突破生效,50)`。
- `有效攻速=min(max(HITSPD,0),个人阈值,50)`。
- `ChangeSpeed 2 修正=有效攻速-max(HITSPD,0)`。
- 实例显示使用绑定60，Value1=40，Value2=真实突破，Value3=0。
- TextVar40固定为 `{攻速突破∶|251}+$$2`，实例汇总读取第二输出。

## 做装备接入

- `script_properties.json` 增加“攻速突破”，最小值0、最大值30。
- 显示写入使用 `SetCustomItemValueEx` 的TextVar模式，不占用普通40至55显示位。
- 固定装备按名称生成 `CHECKITEMW` 分支，多件逐项累加到 `N$XY_AS_FIXED_BREAK`。
- QFunction统一重算入口每次先清零固定装备汇总、执行唯一做装备锚点，再调用外部核心。
- 外部核心把实例TextVar40汇总与固定装备汇总相加后统一封顶；全服仍只有该核心包含活动 `ChangeSpeed 2`。
- 目标服缺少本包受管标记时，使用“攻速突破”的装备预检阻止，不生成只有说明文字的装备。

## 事务和冲突门禁

- 流程：detect → preflight → plan → backup → install/update → verify → rollback。
- TextVar40非空且不是合同文本时阻止。
- 三个事件标签、统一重算标签、包变量、受管标记重复或内容漂移时阻止。
- 除本包核心外发现活动 `ChangeSpeed 2` 时阻止。
- 脚本输出GB18030/CRLF；重复预检幂等；回滚只移除本包受管内容并逐字节恢复独占核心。

## 不纳入内容

- UserCmd100至103、`@攻速测20/40/50`、测试木剑和诊断消息。
- 数据库写入、客户端资源、引擎启动/关闭/重启。

