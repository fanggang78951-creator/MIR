# 狂暴系统（单一NPC入口，可迁移地图）

当前候选版本：3.2.0-candidate.1

成果包ID：`xy.optional.rage.core`  
版本：`3.2.0-candidate.1`  
状态：`candidate/optional`

## 唯一权威

本版本只认一条“狂暴之力”NPC注册和“狂暴之力”称号；NPC可由安装参数迁移地图：

- 唯一实体NPC调用 `狂暴NPC接口.txt@XY_RAGE_NPC_MAIN`；
- QFunction公共命令 `@XY_RAGE_COMMAND` 调用同一接口；
- 左上狂暴图标也调用同一接口；
- 是否已经开启只用 `CHECKFENGHAO 狂暴之力` 判断；
- 不再使用 `N$XY_RAGE_ACTIVE`，不再用另一套 `POWERRATE` 后台赋值。

因此NPC、图标和命令不会各自扣费，也不会出现“货币不足但图标变彩”“重复扣费却没有称号属性”的两套状态冲突。

## 平台入口

图形平台：进入“非常驻脚本”，使用“预检狂暴”与“一键安装狂暴”。  
CLI：

```powershell
D:\XuanYuanDevPlatform\bin\xydp-cli.exe rage-preflight --server D:\NewMirServer
D:\XuanYuanDevPlatform\bin\xydp-cli.exe rage-install --server D:\NewMirServer --yes
```

独立安装默认NPC注册：

```text
玄渊运营/狂暴之力    地图0    322,272    外观15
```

安装参数可改NPC脚本名、显示名、地图、坐标、外观、开启费用和击杀奖励；业务逻辑仍只能保留一份。
平台使用独占脚本路径注册；迁移到 `xycamp` 时会替换同一路径的地图0注册，不会留下两个可见NPC。业务脚本内容不因迁移而改变。

## 对外接口

推荐入口：

```text
@XY_RAGE_COMMAND
```

脚本直接调用：

```text
#CALL [\玄渊功能\狂暴\狂暴NPC接口.txt] @XY_RAGE_NPC_MAIN
```

其他NPC和屏幕图标只能调用以上接口，不得复制 `CHECKGAMEGIRD`、`GAMEGIRD -`、`GIVEFENGHAO`、属性或死亡处理。

注意：本引擎的精确余额检查按“余额大于消耗减一”表达。例如消耗100时使用
`CHECKGAMEGIRD > 99`。`rage_cost_threshold` 必须始终等于 `rage_cost - 1`；
核心标签必须保留外层 `{...}`，否则被 `#CALL` 调用时可能出现 load fail。

## 属性与生命周期

- 开启：扣除原生货币灵符后授予“狂暴之力”称号；余额读取`<$GAMEGIRD>`。
- 重复开启：称号存在时阻止，不再次扣费。
- 费用不足：不授予称号，也不刷新成彩色图标。
- 属性：暴击+10%，爆率+300，最大爆率+5，生命+10000，攻魔道+50-50。
- 被玩家击杀：回收称号，击杀者获得配置的账户金刚石奖励。
- 图标颜色：直接读取称号；登录、成功开启和死亡清理都会刷新。

## 旧版本迁移

升级时平台会在正文哈希完全匹配的前提下：

- 移除旧后台的 `AttackDamage` 与 `PlayOffLine` 狂暴钩子；
- 将旧 `xy.ops.rage-title` 的三类爆率锚点接管到本包；
- 移除旧称号包的重复死亡钩子；
- 将原 `@XY_RAGE_COMMAND` 和属性图标改为调用唯一NPC业务接口。

发现旧钩子被手工改过时必须阻止，不能猜测删除。`狂暴界面刷新接口.txt` 是带 `{ ... }` 的受管可调用空桩；属性图标包追加的刷新钩子位于花括号内部，单独升级狂暴时必须保留。旧 `狂暴核心.txt` 与 `狂暴配置.txt` 即使作为回滚残件保留，也不再有任何运行时引用。

## 验收

至少验证：未开启为黑白、登录已有称号为彩色、点击图标出现与地图0 NPC相同对话、费用不足不变彩、成功只扣一次、重复开启不扣费、称号属性有效、被玩家击杀后变黑白、击杀奖励正确、重复预检零变化、逐字节回滚。
