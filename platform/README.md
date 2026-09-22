# 玄渊翎风成果植入平台

## 艾尔登法环全 NPC 批量包（candidate）

“脚本配置同步”页已增加“NPC 批量包”，可直接选择 ZIP 或已解压目录，完成一次统一预检、一次确认安装和一个总事务回滚。它复用平台现有业务核心，并以工作簿完整相对路径区分同名21/22/34表。当前目标为 `D:\MirServer`、`E:\11周年`与 `D:\素材文件夹\LFM2[20260707]\登录器`。命格、独立材料回收、地图和怪物明确排除。安装只代表“已部署待游戏实测”，不自动发布 `current-release.json`。详见 `接口\51_艾尔登法环全NPC批量包接口.txt`。

独立母库位置：`E:\XuanYuanDevPlatform`。平台只支持翎风/LFM2，不依赖 `D:\MirServer` 固定路径。

当前世界地图导航包为 `xy.ui.world-map 1.0.0-candidate.19`：13 个区域的传送落点统一位于对应赐福点正下方一格，并已按实际 MAP 文件确认可行走；安装时通过受管 `mapinfo_flag` 操作给 13 张地图追加整图 `SAFE`，保留 MapInfo 原有参数。该版本的 WZL/WZX 与 candidate.18 字节相同，不需要仅因本次脚本更新重新生成登录器。

## 快速使用

1. 双击 `Start_XuanYuanDevPlatform.bat`，或直接运行 `bin\XuanYuanDevPlatform.exe`。
2. 在“目标管理”选择新服务端根目录；地图包另选客户端根目录。
3. 在“成果包库”勾选功能或整套预设，候选包需开启“显示候选包”。
4. 先生成预检报告；冲突必须处理后才能安装。
5. 确认安装后，平台自动备份并产生事务收据；“安装历史/回滚”可逐字节恢复。

“NPC编辑”现有“初始之地七NPC”入口。它读取 `所需材料表格汇总` 下七份独立XLSX，在 `xycamp` 出生点 `25,28` 附近自动选择可走空位，并把七个NPC、MerChant、公共狂暴/捐献核心、材料配置、称号链、圣律之剑/黄金圣物升级及新手礼包纳入同一事务。NPC显示名、消耗、当前装备、下一装备、礼包码和两件奖励只认XLSX；平台源码仅保留稳定内部路径。1.8.0-candidate.1继续使用“只显示下一档”界面，并新增已验收的引擎原生转生合同：进度只认`CHECKRENEWLEVEL`，升级使用`RENEWLEVEL 1`，转生称号仅作显示镜像；04表的每档神力增加同时生成静态与攻击前双重算，1至10重累计+5%至+50%。02_捐献.xlsx结构化属性链仍把攻/魔/道写称号定义、暴击写原生称号属性0、基础爆率与最大爆率写统一重算锚点；历史错误钩子只有哈希完整时才安全接管清理。下一件装备使用目标服唯一`StdItems.Idx`生成右侧`ItemShow:0:260:-90:1`，鼠标悬停直接读取真实装备属性；穿戴中的装备不参与识别。表格中的`灵符`、`账户灵符`、`原生灵符`统一解释为翎风原生GAMEGIRD，货币列中的`金币`统一解释为原生金币，普通材料名仍按背包物品处理。赞助与捐献的服务端`ItemDescList.txt`及客户端`data\fenghao.dat`说明纳入同一事务。转生只有在原生等级确认增加后才扣费并清理旧称号；失败不扣费。圣律之剑和黄金圣物属性完全读取目标服`StdItems`，平台不写属性。新手礼包默认码888888，每个角色限领一次，同时发放绑定的圣律之剑LV1和黄金圣物LV1。未填完整的功能只显示“待配置”，不会扣材料或收发装备。

平台现有独立“脚本配置同步”页面。用户从 `所需材料表格汇总` 主动选择刚修改的已登记 `.xlsx/.txt/.csv`，平台通过 `00_填写文档注册表.json` 精确路由，不扫描目录。01至07支持按所选功能局部预检和事务植入；例如选择 `02_捐献.xlsx` 不会重建其余六个NPC。捐献/赞助的历史共享受管钩子会读取02和03表共同保全，但不重建未选NPC。08至13仍转交地图、装备、技能强化或处决实验室专用核心；14至16走各自登记成果链。预检记录来源哈希，确认植入前再次核对；目标或来源变化即阻止，成功后支持逐字节回滚。CLI对应 `config-sync-preflight`、`config-sync-install --yes` 和 `config-sync-rollback --yes`。

`37_命格系统.xlsx` 已登记到脚本配置同步的 `mingge-system` 路由，只能从该页面或现有三条 `config-sync-*` CLI 完成预检、安装和回滚。`xy.optional.mingge-system` 仅是 executable-free 的 candidate 描述包，普通成果包安装入口不得使用；预检固定核对唯一“鞭尸灵玉”、`StdMode=90`、装备位 `17`，安装后须重载 M2 脚本并完成独立测试服游戏验收。完整合同见 `接口\39_命格系统表格与一键植入接口.txt`。

平台新增独立“装备回收”页面，唯一业务母表为 `所需材料表格汇总\19_装备回收配置.xlsx`。同一分类ID的多件装备共用一个玩家勾选项；新增分类ID会自动增加一个条目，每页固定3类并自动分页。每件装备可同时填写一组主奖励和一组附加奖励；脚本只删除一次装备，再分别发放两种奖励。每组奖励都可选原生金币、原生元宝、原生灵符、原生金刚石或背包材料；附加奖励三格全部留空时保持旧版单奖励行为。预检会核对目标StdItems名称唯一性、奖励材料、分类标志位、按钮21、OnTimer20、重复标签和旧候选块哈希；确认更新事务化写入QFunction、QManage与UserCmd。M2运行只警告，不阻止生成；何时重载由用户决定。

正式模式只使用 `verified` 包。`candidate` 表示仍需独立测试服的 M2 启动和游戏内验证，不应植入交付服。

空白翎风服的 `QFunction-0.txt` 可能没有战斗事件标签。`xy.combat.core` 1.2.0 会在预检计划中安全补齐缺失的 `PlayLogin`、`TakeOnEx`、`TakeOffEx`、`AttackDamage`、`KillMon` 最小入口；已有同名事件不改写，重复标签和被手工修改的平台入口仍会阻止安装。

## 当前成果包

- `xy.combat-suite`：神力、打怪伤害、爆伤、爆率/最大爆率、首尾刀和鞭尸。处决试验尚未加入战斗套件。
- `labs\execution`：处决、失衡与韧性独立实验室。只在 GUI“处决测试”页面或 `execution-*` CLI 使用，拥有独立包库、目标状态与备份目录，不会出现在成果包库、一键常驻基础或生产装备工具中。
- `xy.combat.drop` 1.2.0 与 `xy.combat.runtime-refresh` 1.1.0：普通爆率和最大爆率是两个独立乘区，正式公式为`(100+普通加成)*(100+最大加成)/100`；两个`+500%`得到3600，即36倍。旧1000上限和LARGE截断路线已废止。
- `xy.native.initial-bag-200` 2.0.0-candidate.1：常驻候选包；向真实游戏登录脚本的`登陆设置`事件安全植入`ExtBagPageCount = 4`和`ExtBagOpenItemCount + 160`，按基础40格+160扩展格得到200格。缺少真实登录标签时阻止，不自建假入口。
- `xy.ops.first-pick` 1.0.3：首爆首次拾取系统，当前为 `verified/optional`；入口调用公共标签，奖励配置和已领取状态在目标已存在时逐字节保留，不进入一键常驻基础。
- `xy.optional.rage.core` 3.2.0-candidate.1：平台唯一活动狂暴包；唯一NPC、命令和图标共用`@XY_RAGE_NPC_MAIN`，开启费用读取XLSX数量并使用原生`GAMEGIRD`灵符，击杀者账户金刚石奖励保持原业务不变。
- `xy.optional.donate.core` 2.3.1-candidate.1：平台唯一活动捐献包；同一包包含业务脚本、配置合并、受保护状态文件和`@XY_DONATE_COMMAND`公共接口。新服事务创建`玄渊数据\xy_donate\捐献状态.txt`，已有服以`preserve_existing`逐字节保留累计数据；核心不再运行不可靠的`ForceDirectories/CreateFile`。本包不创建NPC、图标、称号或数据库记录。
- `xy.optional.mingge-system` 1.0.0-candidate.1：37_命格系统.xlsx 的可发现描述包；自身不携带安装操作，只能经 `mingge-system` 配置同步路由安装，当前待游戏验证。
- `xy.optional.recycle.configurable` 1.0.0-candidate.6：表格驱动装备自动回收；每个装备分支先无条件清零计数，再检查背包物品，避免沿用上一件实际回收数量。专项页面读取19号中文母表，动态生成分类勾选、三类一页分页、阈值检测、实际删除计数和多奖励类型。
- `xy.optional.recycle.drop-filter`：独立的掉落信息开关候选包，封装翎风原生`FILTERGLOBALMSG 1 1/0`。它不属于回收表格业务，仍可由背包功能服务单独调用。
- `xy.optional.bag.function-service`：背包“功能服务”候选入口包，占用`DBagCustomButton4`/按钮23，打开公共菜单并调用掉落信息包的明确开/关标签；依赖自动补齐，不复制过滤逻辑，后续其他功能继续扩展同一菜单。
- `xy.ui.attr-overview` 2.0.6-candidate.1：左上五图标状态与三组属性总览；声明式`title_additions`可用`CHECKFENGHAO`把赞助称号计入显示值。它只负责显示镜像，不复制伤害、爆率、处决或韧性实效公式，当前为`candidate/optional`。

狂暴和捐献都不会进入“一键安装常驻基础”。“非常驻脚本”页分别提供预检、安装和回滚按钮；每项只安装一个成果包。旧NPC版、旧称号数据库版、独立command适配包和旧运营套件已退出活动库。NPC脚本直接`#CALL`核心触发标签，屏幕图标从`CustomButtonClick`跳到公共QFunction标签；入口不得复制业务规则。两包在独立测试服验收通过前保持candidate，不得植入交付服。各自的完整使用方法和接口命令位于包内`README_使用说明.md`。

平台现已加入“批量做装备”页面。正式中文母版位于 `所需材料表格汇总\09_装备批量生成.xlsx`，默认目标为 `D:\MirServer`，也可浏览选择任意同引擎服务端。旧 `做装备\templates\XuanYuanItems.xlsx` 仅作兼容回退。原装备属性、固定三表和脚本接口由迁入兼容核心保持；正式生成前先在临时副本中处理并验证，失败不写目标服，成功后可按事务逐字节回滚。当前状态为 `candidate`，仍需独立新服完成 M2 和游戏内验收。

共享装备母表已加入`吸血`、`每秒回血`。吸血按对怪本次实际攻击伤害百分比解释，由常驻候选包`xy.combat.sustain`在共享`[@Attack]`事件中按`<$PKPOWER>`即时计算并回血，不再使用有持续时间的`ChangeState 10`；每秒回血按固定生命/秒解释。固定回血使用已通过游戏实测的个人定时器`SetOnTimer 19 1`，并在QManage中把XLSX数值直接写成`HumanHP + 固定值`，不通过动态变量传值，也不使用普通DELAYGOTO自循环。本包自行安全确保四个所需事件标签，单独升级不会重放旧战斗核心；显示镜像分别使用BindType 54、55，ItemDescList仍写入同名绿字说明。

同一页面现提供独立的“材料源表”流程，正式中文母版为 `所需材料表格汇总\11_材料批量生成.xlsx`。填写材料名称和客户端 `Items.wzx` 来源编号后，点击“预检材料 → 确认添加材料”；重量、价格、颜色可以留空。预检会跳过目标服已经存在且 `StdMode=46` 的同名材料，只生成尚未存在的材料；旧材料不覆盖、不重复添加，整表已存在时安全零写入，同名非材料仍阻止。平台固定采用 `StdMode=46`、`Shape=1`、`OverLap=2`、`DuraMax=99999`；材料只要求背包里有图，所以来源编号只读取 `Items.wzx`，事务只修改 `Items.wzl/.wzx`，不读取、不检查、也不修改 `DnItems` 或 `StateItem`。材料不会写入 QFunction、固定属性表或装备备注。该叠加上限已通过引擎文档和数据库字段静态检查，实际单格 99999 仍需在测试服用 `@make 材料名 99999` 完成游戏验收。

处决尚未通过真实游戏验收，所以正式装备母表与生产属性注册表不含“处决概率、韧性”。带这两列的试验草稿只保存在 `labs\execution\equipment`，不得用于正常一键生成装备；处决脚本验收通过后再正式迁入。

“目标管理”底部现提供“国王模式完整一键安装（初始端）”。选择新服务端和配套客户端后，点击“一键安装国王模式”，平台会在一个事务中安装 `T218` 死亡神殿大厅、A/B野区、`XYGDZY`角斗场、六个NPC、A/B国家、国王称号、报名与五波流程、复活与击杀结算，以及国王模式必需的神力倍攻、暴击伤害、战斗公共入口和运行时刷新常驻链。正式成果包为 `packages\verified\xy.optional.king-mode.complete` 2.1.1；多帧称号登录和切换时仅通过 `CheckActiveFengHao` 同步玩家当前展示，不授予、不激活、不回收称号。数值母表位于目标服 `Mir200\Envir\QuestDiary\玄渊配置\国王模式配置.txt`；编辑后点击“读取并应用配置TXT”重新渲染，M2运行时不直接读取配置。完整正确成果见 `knowledge\国王模式\国王模式完整一键安装正确成果.md`。

“批量做装备”的生成和修改现共用 `所需材料表格汇总\09_装备批量生成.xlsx`。生成点击“预检 → 确认生成”，修改点击“预检修改 → 确认修改”，两种计划不能互相误执行。新建装备直接使用来源编号作为最终 Looks，只读校验 Items/StateItem/DnItems 三套同号图片，客户端六图库零写入，不再向尾部复制图片；多个装备可共用同一 Looks。装备持久固定为 60000；修改时部位可留空自动识别，来源编号留空保留旧 Looks，填写则事务化更换三套静态图并保持 Shape/StdMode。旧 10 号修改表只作兼容归档，不再作为输入。

装备美术素材库现有 `做装备\assets\equipment-icons\玄渊三十套九部位_270件_v1`。它用三张九件母版在本地派生 30 套、270 件静态素材，并同步生成 `Items`、`StateItem`、`DnItems` 三种 24 位 BMP。包内导入器先生成完整临时图库并逐帧回读，确认后成对备份六个 WZL/WZX 再原子提交；同一件装备在三套图库中保持同一个来源编号。用户交付统一使用按套装分组的 `装备素材套装代码表.xlsx`，每行九个部位，不再输出 TXT 代码表。该流程不修改数据库、属性、爆率、脚本或角色动作帧。

生肖槽位素材独立存放于 `做装备\assets\equipment-icons\玄渊十二星宫生肖槽位_12件_v1`，使用 12 个不含具体动物图案的星宫图标，代码为当前客户端 `6246-6257`。它与普通九部位装备素材分开编号、分开代码表，但仍按 Items/StateItem/DnItems 三库同号规则导入；不自动创建生肖属性、套装效果或脚本。

## 通用物品合成

通用合成使用两份中央配置：`所需材料表格汇总\34_通用物品合成.xlsx`填写配方、产出与消耗，`35_合成NPC与配方分配.txt`填写NPC、地图、坐标以及配方ID归属。支持同图多个独立NPC和跨地图NPC，每个NPC只显示分配给自己的配方。NPC主页面与确认页面按目标服真实物品编号显示合成产物，首个图标使用已验收的对话框内部坐标`X=260、Y=-30`，鼠标悬停可查看真实属性。配置同步选择任一文件都会自动联读另一份，并以单一事务完成预检、备份、植入和回滚。

## 装备范围光环（candidate）

独立“装备光环”页面读取 `所需材料表格汇总\36_装备范围光环.xlsx`。先输入关键字搜索目标服真实 `StdItems.Name`，再从10套预览中选样式，填写伤害倍率、间隔和优先级，点击“写入/更新绑定表”。所有样式均采用已验收圆月斩供体的完整尺寸、8帧30ms结构，固定视觉和伤害范围3格；不同样式只改变颜色与光影，不降低资源质量。

运行时只有一个 `OnTimer97`、一条 `RangeHarm` 伤害出口和一个平台受管核心；同一人物意外同时穿戴多件光环装备时只启用优先级最高的一件。安全区内停止本系统视觉与伤害，离开后恢复；登录、穿戴、卸下、死亡、复活和换图均调用公共刷新接口。预检会验证目标装备唯一性、共享事件、定时器、受管块、资源编号、客户端和登录器静态资源；确认部署前复核所有哈希，失败零半成品，事务可逐字节回滚。当前默认服务端 `D:\MirServer`、客户端 `E:\11周年`、登录器目录 `D:\素材文件夹\LFM2[20260707]\登录器`。平台不会操作M2或游戏引擎。

## 常驻基础与非常驻脚本

- 成果包可声明 `residency=resident` 或 `residency=optional`；旧包默认 optional。
- “成果包库”的“一键安装常驻基础”会收集全部 resident 包，先预检并列出候选包，确认后才写入目标服。
- “非常驻脚本”页面支持选择原始脚本文件夹或完整成果包文件夹。原始文件必须附带使用说明，首次只登记待验证；完整成果包校验后可正常预检、安装和回滚。
- 固定母库为 `非常驻脚本`，完整操作见 `knowledge\常驻与非常驻脚本使用说明.md`。
- 狂暴和捐献使用 `config_merge` 安装默认配置：保留已有值，只补缺失节和键。两包始终为 `optional`。
- 装备回收通过独立“装备回收”页读取19号母表，不进入常驻基础。“装备名称”可用`|`或单元格换行填写多件，同格装备共享本行奖励并逐件精确预检。旧固定白名单、独立auto/bonus和bag-entry只作历史兼容，不得与新表格包并行；掉落屏蔽仍为独立可选包。权威接口见`接口\24_装备回收表格配置接口.txt`。
- 常驻战斗核心使用事务化 `config_set` 默认开启 `SendItemDescList` 与 `SendTzItemDescList`；只修改这两个 M2 物品备注发送开关，重复安装幂等。

## 命令行

```powershell
bin\xydp-cli.exe list-packages
bin\xydp-cli.exe equipment-aura-list-styles
bin\xydp-cli.exe equipment-aura-preflight --server D:\MirServer --client E:\11周年 --login "D:\素材文件夹\LFM2[20260707]\登录器" --input E:\XuanYuanDevPlatform\所需材料表格汇总\36_装备范围光环.xlsx
bin\xydp-cli.exe equipment-aura-install --server D:\MirServer --client E:\11周年 --login "D:\素材文件夹\LFM2[20260707]\登录器" --input E:\XuanYuanDevPlatform\所需材料表格汇总\36_装备范围光环.xlsx --yes
bin\xydp-cli.exe equipment-aura-rollback --server D:\MirServer --transaction 事务号 --yes
bin\xydp-cli.exe preflight --server D:\NewMirServer --package xy.combat.power
bin\xydp-cli.exe execution-preflight --server D:\ExecutionTestServer
bin\xydp-cli.exe execution-install --server D:\ExecutionTestServer --yes --confirm-test-server
bin\xydp-cli.exe execution-rollback --server D:\ExecutionTestServer --yes
bin\xydp-cli.exe preflight --server D:\NewMirServer --package xy.ops.first-pick
bin\xydp-cli.exe install --server D:\NewMirServer --package xy.combat.power --yes
bin\xydp-cli.exe rollback --server D:\NewMirServer --transaction 事务号 --yes
bin\xydp-cli.exe resident-preflight --server D:\NewMirServer
bin\xydp-cli.exe rage-preflight --server D:\NewMirServer
bin\xydp-cli.exe rage-install --server D:\NewMirServer --yes
bin\xydp-cli.exe rage-rollback --server D:\NewMirServer --yes
bin\xydp-cli.exe donate-preflight --server D:\NewMirServer
bin\xydp-cli.exe donate-install --server D:\NewMirServer --yes
bin\xydp-cli.exe donate-rollback --server D:\NewMirServer --yes
bin\xydp-cli.exe recycle-config-search --input E:\XuanYuanDevPlatform\所需材料表格汇总\19_装备回收配置.xlsx --keyword 木剑
bin\xydp-cli.exe recycle-config-preflight --input E:\XuanYuanDevPlatform\所需材料表格汇总\19_装备回收配置.xlsx --server D:\NewMirServer
bin\xydp-cli.exe recycle-config-apply --input E:\XuanYuanDevPlatform\所需材料表格汇总\19_装备回收配置.xlsx --server D:\NewMirServer --yes
bin\xydp-cli.exe recycle-config-rollback --server D:\NewMirServer --transaction 事务号 --yes
bin\xydp-cli.exe script-folder-list
bin\xydp-cli.exe equipment-inspect --input E:\XuanYuanDevPlatform\所需材料表格汇总\09_装备批量生成.xlsx
bin\xydp-cli.exe equipment-material-preflight --input E:\XuanYuanDevPlatform\所需材料表格汇总\11_材料批量生成.xlsx --server D:\NewMirServer --client-data D:\Client\data
bin\xydp-cli.exe equipment-material-apply --input E:\XuanYuanDevPlatform\所需材料表格汇总\11_材料批量生成.xlsx --server D:\NewMirServer --client-data D:\Client\data --yes
bin\xydp-cli.exe king-mode-flow-preflight --server D:\MirServer --client E:\11周年
bin\xydp-cli.exe king-mode-one-click --server D:\MirServer --client E:\11周年 --yes
bin\xydp-cli.exe king-mode-config-apply --server D:\MirServer --client E:\11周年 --yes
bin\xydp-cli.exe king-mode-rollback --server D:\MirServer --yes
bin\xydp-cli.exe initial-camp-preflight --server D:\NewMirServer --materials E:\XuanYuanDevPlatform\所需材料表格汇总
bin\xydp-cli.exe initial-camp-install --server D:\NewMirServer --materials E:\XuanYuanDevPlatform\所需材料表格汇总 --yes
bin\xydp-cli.exe initial-camp-rollback --server D:\NewMirServer --yes
bin\xydp-cli.exe seal-title-preflight --server D:\NewMirServer --materials E:\XuanYuanDevPlatform\所需材料表格汇总
bin\xydp-cli.exe seal-title-install --server D:\NewMirServer --materials E:\XuanYuanDevPlatform\所需材料表格汇总 --yes
bin\xydp-cli.exe seal-title-rollback --server D:\NewMirServer --yes
```

完整接口见 `knowledge\成果包开发规范.md`，迁移规则见 `knowledge\AI_Handoff迁移规则.md`。

## 神印基础属性与称号晋升双NPC（已验收）

NPC编辑页的“神印与称号双NPC”读取中央母表 `21_神印基础属性.xlsx` 与 `22_称号晋升.xlsx`。21号表按用户提供规划保留完整200层，逐层用 `ChangeHumAbilityEX 5-11` 增加基础攻魔道上下限和HP，不授予称号、不进入任何乘区。22号表采用单档逐级称号界面，固定顺序为授予新称号、确认成功、扣除资源、回收旧称号。

当前22号表已有10个正式名称、攻魔道、HP、MP、基础爆率及消耗；称号编号使用100至109，MP逐档与HP相同，10行状态均为“可安装”。编号已核对当前目标服和平台登记未占用，安装前仍会再次预检数据库冲突。正式2.0.1统一使用`HUMAN XY_SEAL_BASE_LEVEL`与`QuestDiary\XY_System\XuanYuanHumanVar.txt`保存人物档位；用户已完成升级、小退和重读验收。旧`N$`与`SAVEVAR HUMAN`混合路线禁止参考。该专项事务保持独立，不自动替换现有 `xy.ops.title`。

## 怪物库 V3（后续默认路线）

当前怪物库以 V3 为后续默认路线，并明确区分两种引擎模式：`standard_appr` 适用于普通 Appr 资源链；`smartmonster` 适用于 RaceImg=156 的 SmartMonster INI、EffectImageList 与多资源闭包。闭包不完整、复杂能力或未验证模型必须标为 `unsupported`/`candidate`，不能进入默认随机或安装路径。星辰怪13已完成身体及站立、行走、攻击、受击、死亡五类动作游戏验收；它只保留为 V3 黄金证据和回滚参照，不再作为后续批量入口。

最简用户流程：保存并彻底关闭 XLSX -> 在“怪物库”执行 V3 预检 -> 一键同步 -> 按预检说明人工生成 DAT -> 在登录器中集成自定义怪物配置 -> 使用新登录器进行身体和五类动作游戏验收。平台不替代人工 DAT/登录器步骤；缩略图仅用于预览，不能证明补丁完整、闭包可用或登录器已集成。该路线只管理怪物资料与补丁，不新增刷怪、MonGen 或爆率。

V2 `catalog.sqlite` 检测到后不得猜测升级：重建前会按 SHA-256 创建并回读内容寻址备份；相同哈希的文件复用既有备份，大资产不得整库复制。V3 隔离验证和平台打包回归完成前保留该回滚入口。

### 历史兼容说明

GUI 的“怪物库”页会把明月供体中每一条有效 Monster 数据行、正确动作补丁、资源哈希和PAK密码沉淀到 `怪物库`。翎风实测映射统一为 `library_no = Appr // 10 + 1`、`slot_no = Appr % 10`；例如 Appr1230 必须读取 Mon124，旧 `Appr // 10` 路线已废弃并禁止参考。

这段 V2 兼容资料只保留映射与资源核对背景，不提供安装、回滚或表格应用命令。所有后续操作都以上述 V3 流程为准：只管理怪物资料与补丁，不新增刷怪、MonGen 或爆率。

## 完整成果母库

2026-07-10 起，平台不再只保存少量成果包证据，还保存两处施工来源的完整只读副本：

- `library\sources\codex_handover`：来自 `D:\codex交班记录`，普通内容为正式优先来源。
- `library\sources\legacy_ai_handoff`：来自 `D:\MirServer旧\AI_Handoff`，保留脚本、技能、工具、UI、图片、二进制素材和历史证据的原目录结构。
- `library\reviewed\deepseek`：DeepSeek 材料的审核视图，分为 `verified`、`candidate`、`reference`、`deprecated`。
- `catalog\artifacts.json`：每个文件的源路径、母库路径、SHA-256、来源优先级和全部冲突变体。
- `catalog\deepseek_review.json`：DeepSeek 逐文件审核结论和证据。

同名不同内容不会互相覆盖。普通交班记录优先于旧 AI_Handoff；DeepSeek 内容必须按审核状态决定优先级，废弃与错误输出永不成为母版。原来源只复制，不移动、不删除。

完整母库是“成果原料和证据仓”，只有已经整理为 `packages\verified` 或 `packages\candidate` 的成果包才能在 GUI 中一键植入服务端。不能把 8439 个历史文件不经冲突分析就直接写入新服。

管理员可用源码版或新构建的 CLI 重跑提取；命令必须显式提供 `--yes`：

```powershell
bin\xydp-cli.exe extract-library --codex D:\codex交班记录 --legacy D:\MirServer旧\AI_Handoff --deepseek D:\codex交班记录\deepseek专用 --decisions E:\XuanYuanDevPlatform\knowledge\deepseek_review_decisions.json --yes
```
