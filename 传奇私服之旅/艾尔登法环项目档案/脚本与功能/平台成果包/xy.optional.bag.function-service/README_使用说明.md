# 背包功能服务（掉落信息开关）

状态：`candidate / optional`。

本包把背包第四个预留按钮“功能服务”接到一个公共菜单：

- UI 控件：`DBagCustomButton4`
- 引擎按钮编号：`23`
- 点击事件：`[@CustomButtonClick]`
- 公共菜单：`@XY_BAG_FUNCTION_SERVICE_PANEL`
- 当前菜单项：开启屏蔽掉落信息、关闭屏蔽掉落信息

本包依赖 `xy.optional.recycle.drop-filter`，菜单只调用依赖包的公共标签：

- `@XY_RECYCLE_DROP_FILTER_ENABLE`
- `@XY_RECYCLE_DROP_FILTER_DISABLE`

它不复制 `FILTERGLOBALMSG` 逻辑，也不改变掉率、地面物品、回收白名单或背包 UI。以后增加其他背包功能，应升级本包的同一个公共菜单，不要再占用按钮 23 或另建重复入口。

## 安装与验收

1. 在成果包库勾选“显示候选包”，选择本包。
2. 先生成预检报告；平台会自动补齐掉落过滤依赖。
3. 确认目标服没有其他 `CustomButtonID 23` 处理分支后再安装。
4. 让 M2 重载脚本或由用户正常重启后重新登录。
5. 打开背包，点击“功能服务”，应出现两个开关。
6. 开启后测试掉落物仍存在、真实掉率不变，但全服掉落提示不再显示；关闭后提示恢复。

当前缺少游戏内按钮点击与两种状态验收证据，因此必须保持 `candidate`。
