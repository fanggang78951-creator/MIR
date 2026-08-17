# 十三大陆图形装备收集图鉴

成果包 ID：`xy.optional.equipment-collection`  
版本：`1.0.0-candidate.10`  
状态：`candidate`  
常驻属性：否，属于可选功能。

## 正式母版

- 唯一配置：`D:\XuanYuanDevPlatform\所需材料表格汇总\33_装备收集图鉴.xlsx`
- 编译核心：`D:\XuanYuanDevPlatform\src\xydp\equipment_collection.py`
- 接口说明：`D:\XuanYuanDevPlatform\接口\33_装备收集图鉴接口.txt`
- 通用界面资源：`D:\XuanYuanDevPlatform\labs\equipment_collection\graphical_candidate\build`

## 为什么包内没有固定 QFunction 脚本

装备图标必须按目标服务端 `StdItems.Name` 唯一解析该服真实 `Idx`。不同服务端的 `Idx` 可能不同，因此不能把某个测试服生成的 QFunction 或装备编号作为母版复制。

本成果包是专项配置型成果包，`install_route` 固定为 `equipment-collection`。在普通“成果包库”中可以看到它，但普通成果包安装核心会阻止直接植入，避免形成没有目标服装备解析结果的空安装。

## 正确安装方法

1. 编辑33号母表，填写准确装备名称、大陆、顺序、消耗和奖励。
2. 打开平台“脚本配置同步”。
3. 选择 `33_装备收集图鉴.xlsx`。
4. 选择服务端和客户端，执行预检。
5. 核对目标服真实 `StdItems.Idx`、状态位、UserCmd、脚本锚点和客户端资源计划。
6. 用户确认后执行事务安装。
7. 由用户自行重载或重启M2，再用 `@装备收集` 游戏验收。

## 安全契约

- 不复制供体装备 `Idx`、Shape、Looks或装备图库。
- 装备名称不存在、重名、状态位冲突、命令号冲突、锚点缺失或客户端资源冲突时整次阻止。
- 安装前备份全部受影响文件；失败零写入；支持按事务逐字节回滚。
- 收集ID 1至200对应人物状态400至599；分类状态使用600至639。
- 已发布的收集ID不得换绑另一件装备。

## 当前验收状态

- 三件装备逐件点亮、单件奖励、全部点亮奖励和重复领取防护已通过游戏验收。
- 十三大陆动态悬停与 `candidate.10` 的“本页一键收集”仍等待完整游戏验收。
- 未完成上述验收前不得改为 `verified`。
