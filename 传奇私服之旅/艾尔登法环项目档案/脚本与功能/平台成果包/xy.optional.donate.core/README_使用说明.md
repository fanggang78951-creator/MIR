# 沙城捐献（脚本+命令接口）

## 定位

这是平台中唯一活动的沙城捐献成果包。它只植入捐献业务脚本、可保留配置和公共命令接口：

- 不自动创建NPC；
- 不自动创建屏幕图标；
- 不写`MerChant.txt`；
- 不创建“沙城捐献”称号或修改装备数据库；
- NPC、图标及其他入口只调用本包接口，不得复制费用、人物累计、全服累计、榜一或封榜逻辑。

成果包ID：`xy.optional.donate.core`  
当前版本：`2.4.0-candidate.1`  
状态：`candidate/optional`

## 使用方法

### 图形平台

1. 在“目标管理”选择独立测试服务端并识别目标。
2. 进入“非常驻脚本”。
3. 点击“预检捐献”，确认报告中只有核心脚本、配置和QFunction命令接口。
4. 点击“一键安装捐献”并确认。
5. M2重载或重启后，用NPC或屏幕图标调用公共接口。

### CLI

只预检：

```powershell
D:\XuanYuanDevPlatform\bin\xydp-cli.exe donate-preflight --server D:\NewMirServer
```

确认安装：

```powershell
D:\XuanYuanDevPlatform\bin\xydp-cli.exe donate-install --server D:\NewMirServer --yes
```

逐字节回滚最近一次捐献安装：

```powershell
D:\XuanYuanDevPlatform\bin\xydp-cli.exe donate-rollback --server D:\NewMirServer --yes
```

## 接口命令

公共QFunction标签：

```text
@XY_DONATE_COMMAND
```

通用脚本调用命令：

```text
#CALL [\玄渊功能\捐献\捐献核心.txt] @XY_DONATE_TRIGGER
```

两种入口最终调用的是同一个`@XY_DONATE_TRIGGER`，捐献业务逻辑只有一份。

如目标服仍安装旧的`xy.optional.donate.command`受管块，当前包会在预检识别并接管它：旧块必须完整且未手改；正式安装后只保留新的`xy.optional.donate.core`受管块，并清理旧包安装状态。新旧块并存或旧块被手改时仍会阻止。

每次触发开始时 `N$XY_DONATE_LAST_SUCCESS=0`，只有实际扣费成功并进入 `@XY_DONATE_APPLY` 后才变为1。需要在成功捐献后授予称号的外壳脚本，必须检查该变量；不能因为外部CALL返回就误判成功。

## NPC调用

NPC对话中建立自己的本地选项标签，再调用公共脚本接口：

```text
[@Main]
#SAY
<我要捐献/@我要捐献>

[@我要捐献]
#ACT
#CALL [\玄渊功能\捐献\捐献核心.txt] @XY_DONATE_TRIGGER
```

NPC地图、坐标、外观和名称由NPC编辑器决定，不属于捐献核心包。

## 屏幕图标调用

在已有`[@CustomButtonClick]`中判断自己的按钮ID，然后跳到公共QFunction标签：

```text
#IF
; 这里填写该图标自己的按钮ID判断
#ACT
GOTO @XY_DONATE_COMMAND
```

图标资源、坐标、三态图片和按钮ID由UI功能决定，不属于捐献核心包。

## 配置

目标文件：`Mir200\Envir\QuestDiary\玄渊配置\沙城捐献配置.txt`。

平台使用缺项合并：已有配置值原样保留，只补充缺少的配置键。不要在NPC或图标脚本里另写费用、累计、榜一奖励或封榜规则。

运行数据固定保存在`Mir200\Envir\QuestDiary\玄渊数据\xy_donate\捐献状态.txt`。成果包在事务安装时创建父目录和0字节初始文件；若目标服已有该文件，`preserve_existing=true`会逐字节保留人物累计、全服累计、榜一与封榜状态，升级绝不以空文件覆盖。核心脚本不再运行`ForceDirectories/CreateFile`，避免父目录创建失败导致扣费后无法保存。

初始之地七NPC入口的称号属性不由本包硬编码，唯一来源是`D:\XuanYuanDevPlatform\所需材料表格汇总\02_捐献.xlsx`。当前母表为：攻/魔/道99-99、原生暴击10%、基础爆率100%、最大爆率5%。初始之地事务会用这些结构化列生成称号定义、原生称号属性0、爆率统一重算钩子及称号说明；以后修改数值只改该XLSX并重新预检。

货币固定表示引擎原生账户货币，不得退化为背包物品：金币使用`CHECKGOLD/GOLDCOUNT`，元宝使用`CHECKGAMEGOLD/GAMEGOLD`，灵符使用`CHECKGAMEGIRD/GAMEGIRD`，金刚石使用`CHECKGAMEDIAMOND/GAMEDIAMOND`。旧配置即使仍写成`消耗类型=材料、消耗名称=灵符`，核心也会按原生灵符处理，绝不会执行`CHECKITEM 灵符`或`TAKE 灵符`。普通材料仍按物品处理。

核心脚本由平台从UTF-8母版转码为GB18030/CRLF写入目标服，禁止直接复制UTF-8脚本到M2目录。

## 验收

至少验证：费用不足、刚好足够、人物累计、全服累计、榜一更新、封榜、奖励、NPC调用、图标调用和逐字节回滚。完成独立新服游戏验收前保持`candidate`。
