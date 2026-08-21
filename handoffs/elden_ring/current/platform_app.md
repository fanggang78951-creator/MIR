# 当前交班｜平台应用窗口

- 窗口名称：平台应用窗口
- 状态：部分完成
- 当前任务：十大陆材料系统的平台对象、来源怪物、掉率和关联装备接续落地
- 当前执行单：`outputs/elden_ring_10_continent_material_system_20260821/06_当前任务单_平台应用窗口_材料系统接续落地.md`
- 开始基线：`2026-08-21 19:38 +08:00`
- 完成时间：`2026-08-21 21:14 +08:00`
- 分支：`codex/elden-ring-c01-v1-20260820`
- 上游脚本窗口提交：`7c4ca82fb8dfac0225d9b171344211416de9dae2`
- 本轮提交SHA：待提交（以包含本文件的最终提交为准）

## 本轮实际完成

- 已同步并逐项复用脚本窗口68种材料Idx，没有另分配编号。
- 批次A形成68条材料平台映射：3条真实数据库复用，65条待本地平台导入；12个匿名预留位固定972—983且未命名。
- 批次B形成32条四证来源映射：32个MapInfo地图号均唯一存在；32个来源地图在MonGen均为0条刷新，实际怪物ID/名称全部保持空值并逐项阻断。
- 批次C形成11件强合成成品、4件装备型四证奖励、44件配方来源装备登记；真实StdItems中均无同名对象，未猜装备Idx、来源编号或模板。
- 4个隐藏称号奖励明确排除，没有伪造成装备。
- 完成物品Idx、地图号、怪物逻辑ID、装备Idx/来源号缺口与跨命名空间审计；真实MapInfo重复定义为`D5071`两条，与本批32个来源地图无直接重叠。
- 保留821→6407、823→6401、824→6403替代关系；真实数据库仅存在旧号821/823/824对象，6407/6401/6403尚未形成对象，未写成已回写。

## 仓库成果

- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/00_上游状态与平台只读预检.md`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/01_材料编号颜色模板映射.xlsx`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/01_材料编号颜色模板映射.json`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/02_材料来源怪物与掉率映射.xlsx`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/02_材料来源怪物与掉率映射.json`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/03_专属装备来源等级登记.json`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/04_强合成与任务奖励装备平台表.xlsx`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/05_平台预检或导入结果.md`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/06_编号重复与交叉冲突报告.md`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/07_交给脚本窗口_平台对象映射.json`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/08_平台变更清单与回滚说明.md`
- `outputs/elden_ring_10_continent_material_system_20260821/platform_app/09_平台映射契约验证.py`

## 平台、数据库与备份

- E盘平台只读核验：材料接口、CLI源码、装备桥接源码和`bin/xydp-cli.exe`存在。
- 数据库：`D:\MirServer\Mud2\DB\ApexM2.DB`，SHA256=`619c32b497530f46251fd962a71e7d8329905ee37ea5ebbcb4bf4e1e3ae41f61`；StdItems 907条，最大Idx 906，907—983占用0条。
- Monster表543条且无独立怪物ID列；MonItems目录98个文件。
- 本轮对E盘平台、D盘服务端、数据库、MapInfo、MonGen、MonItems写入均为0，事务号为无。
- 备份：仓库基线提交`7c4ca82fb8dfac0225d9b171344211416de9dae2`；关键交班临时副本在验证后删除。没有目标写入，因此没有创建数据库/平台回滚包。

## 验证

- `09_平台映射契约验证.py`：通过，覆盖68材料、12预留、32来源、44来源装备、15目标装备与上游SHA。
- 三份XLSX通过Artifact Tool导出回读：工作表数量分别3、2、5；公式错误匹配0。
- Artifact Tool原生渲染尝试未生成PNG；因此没有宣称视觉渲染验收，只保留结构/值/格式的程序化回读。
- 未执行数据库事务、平台应用、M2加载或游戏内验证。

## 未完成与逐项阻断

- 批次A：65条新材料尚未经过E盘平台正式预检、备份、事务应用和数据库回读，状态为`待本地平台导入`。
- 批次B：32条均缺实际怪物ID/名称和MonGen刷新；不得让脚本窗口据逻辑ID猜MonItems或首杀对象。
- 批次C：15件目标装备均缺实际Idx、来源编号和唯一模板；44件来源装备同样缺真实对象。
- 独立`xydp-cli.exe equipment-material-preflight --help`调用超过30秒未返回；没有继续绕过GUI或直接写库。

## 下一步

1. 平台应用窗口先按`01`只导入65条新材料，保留3条复用与12条匿名预留，生成真实事务号和回读证据。
2. 怪物窗口补32条真实Monster身份与MonGen落点后，再解锁`02`。
3. 装备窗口补15件目标装备及44件来源装备的Idx、来源编号、唯一模板后，再解锁`03/04`。
4. 脚本窗口可以读取`07`中的最终材料Idx，但在平台回读完成前不得执行65个新材料名；怪物和装备空值不得消费。

`platform_app phase complete; script window may consume 07 mapping`（按上述状态门槛消费）。
