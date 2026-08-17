# 百分比吸血与每秒回血

包 ID：`xy.combat.sustain`  
版本：`1.2.0-candidate.1`  
状态：`candidate / resident`

本包给做装备工具提供两个严格宿主锚点：

- `XY_EQUIP_MAKER_LIFESTEAL_ANCHOR`：汇总 XLSX 的“吸血”。
- `XY_EQUIP_MAKER_HP_REGEN_ACTIVE_ANCHOR`：在 QFunction 检测是否穿戴回血装备，只写启停标记。
- `XY_EQUIP_MAKER_HP_REGEN_TICK_ANCHOR`：在 QManage 为每件装备写入 XLSX 固定回血值。

事件接入自包含：本包自行安全确保 `PlayLogin`、`TakeOnEx`、`TakeOffEx`、`Attack` 四个事件标签存在，再插入自己的受管钩子。这样单独升级本包不会重放或改写旧 `xy.combat.core` 事件桩；战斗整套包仍同时安装公共核心。

数值语义：

- `吸血=10`：攻击怪物后按本次实际攻击伤害 `<$PKPOWER>` 的 10% 恢复自身生命。路线参照明月端：共享 `[@Attack]` 事件中先确认当前目标为怪物，再用 `CALCPERCENT` 计算并执行 `HumanHP +`；不使用有持续时间的 `ChangeState 10`，也不是武器 Weight 固定点数吸血。
- `每秒回血=100`：角色存活时每 1 秒恢复 100 点生命。使用 `HumanHP +` 固定点数恢复，不按 MaxHP 百分比计算。

生命周期：登录、穿戴和脱下时先启动翎风个人定时器 `SetOnTimer 19 1`，再进入 `@XYDP_RecalcSustain`，重算当前装备的吸血总百分比并根据回血装备启停定时器。每次对怪攻击由受管 `[@Attack]` 钩子即时读取该汇总值回血，不依赖定时状态。QManage 唯一事件 `[@OnTimer19]` 不读取动态回血变量，而是逐件执行做装备工具按 XLSX 生成的 `HumanHP + 固定值`；不同名称装备自然叠加，卸下最后一件回血装备后 `SetOffTimer 19`。编号 19 是本包内部保留位；发现目标服已占用时预检必须阻止。

旧 `XY_EQUIP_MAKER_HP_REGEN_ANCHOR`、`N$XY_SUS_HPPerSec` 和 `HumanHP + <$STR(...)>` 路线已经退役。升级时成果包只声明退役该旧锚点下结构完全匹配的平台五行装备块，普通手写脚本仍受哈希保护并阻止覆盖。

显示契约：吸血使用 BindType 54，每秒回血使用 BindType 55；`ItemDescList` 同时写入同名绿字说明。实效只来自上述宿主锚点，显示值不再次进入汇总。

发布门槛：静态检查、缺失 Attack 标签引导、共享 Attack 正文保留、重复标签阻断、隔离升级、幂等和逐字节回滚已由自动测试覆盖；黄金圣物LV8固定1200点/秒路线已通过游戏内实测。明月式对怪吸血仍需验证单件、多件叠加、穿脱清零、重登恢复、满血不溢出及 PVP 不吸血，才可从 candidate 晋级 verified。
