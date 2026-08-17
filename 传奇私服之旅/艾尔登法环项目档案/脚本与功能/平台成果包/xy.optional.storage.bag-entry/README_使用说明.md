# 随身无限仓库（背包按钮入口）

## 定位

本包只把当前大背包第一个预留按钮“随身仓库”连接到翎风原生无限可视仓库，不创建NPC，不修改客户端界面，也不搬迁仓库数据。

- 成果包ID：`xy.optional.storage.bag-entry`
- 版本：`1.0.0-candidate.1`
- 状态：`candidate/optional`
- UI控件：`DBagCustomButton1`
- 翎风预留按钮编号：`20`
- 引擎命令：`OpenStorageView 1`
- M2前置：功能设置中的无限仓库已经开启，并已设置可存数量

## 事件链

```text
背包“随身仓库”
  -> DBagCustomButton1
  -> [@CustomButtonClick]
  -> <$CustomButtonID> = 20
  -> OpenStorageView 1
  -> 翎风原生无限可视仓库
```

入口钩子固定为：

```text
#IF
EQUAL <$CustomButtonID> 20
#ACT
OpenStorageView 1
BREAK
```

`OpenStorageView 1` 是无限可视仓库；`OpenStorageView 0` 才是普通可视仓库。二者不是同一套存储入口，本包不得改回参数0。

## 平台安装

1. 在M2确认无限仓库已经开启并设置容量。
2. 在平台“成果包库”勾选“显示候选包”。
3. 选择“随身无限仓库（背包按钮入口）”。
4. 点“生成预检报告”，确认只修改 `Mir200\Envir\Market_Def\QFunction-0.txt`。
5. 点“确认安装”，保存事务号。
6. 让M2重载脚本后，打开背包点击“随身仓库”。

CLI：

```powershell
D:\XuanYuanDevPlatform\bin\xydp-cli.exe preflight --server D:\MirServer --package xy.optional.storage.bag-entry
D:\XuanYuanDevPlatform\bin\xydp-cli.exe install --server D:\MirServer --package xy.optional.storage.bag-entry --yes
```

## 验收

1. 点击“随身仓库”，必须打开无限可视仓库。
2. 存入一件测试物品，再取出，数量和属性必须保持。
3. 再存入物品，重新登录后确认仍存在，再取回。
4. 点击“装备回收”，仍只进入玄渊快捷回收页面。
5. “材料回收”和“功能服务”不得误触发仓库。
6. M2日志不得出现重复标签、脚本加载失败或未知命令。

当前包只完成静态、事务、幂等和回滚验证；游戏内点击、存取、重登持久性通过后才能晋级 `verified`。

## 安全边界

- 不执行 `@bigstorage`、`@biggetback`，不建立第二套脚本仓库页面。
- 不修改 `!setup.txt`、仓库容量、玩家仓库数据、数据库或客户端资源。
- 不占用按钮21至24；编号21继续属于“装备回收”。
- 新服若编号20已有其他逻辑，必须先停止并处理冲突，不得直接覆盖。
