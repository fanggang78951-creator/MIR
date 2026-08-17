# 玄渊掉落信息屏蔽（玩家开关）

状态：`candidate / optional`。

这是对翎风原生命令的安全接口封装：

```text
FILTERGLOBALMSG 1 1  ; 屏蔽掉落提示
FILTERGLOBALMSG 1 0  ; 恢复掉落提示
```

## 公共接口

- `GOTO @XY_RECYCLE_DROP_FILTER_COMMAND`：切换开/关。
- `GOTO @XY_RECYCLE_DROP_FILTER_ENABLE`：明确屏蔽。
- `GOTO @XY_RECYCLE_DROP_FILTER_DISABLE`：明确恢复。
- `N$XY_RecycleDropFilterEnabled`：脚本记录的当前开关状态。

本包不自动启用、不修改掉率、不删除地面物品、不改变回收表。NPC、屏幕图标或其他菜单只需跳公共接口。

背包现成入口：安装 `xy.optional.bag.function-service` 后，背包第四个按钮“功能服务”（`DBagCustomButton4` / 编号23）会打开菜单，并分别调用上面的明确开启、明确关闭接口。过滤逻辑仍只由本包维护。

官方说明：`FILTERGLOBALMSG` 的类型 1 是物品掉落提示，第二参数 1 表示过滤，0 表示不过滤。

文档：`https://www.5cq.com/help/%E7%BF%8E%E9%A3%8E/topics/%E6%B8%B8%E6%88%8F%E5%BC%95%E6%93%8E%E5%8F%8D%E5%A4%96%E6%8C%82%E7%B3%BB%E7%BB%9F/%E5%8A%9F%E8%83%BD%E6%93%8D%E4%BD%9C%E5%91%BD%E4%BB%A4/%E8%BF%87%E6%BB%A4%E5%85%A8%E6%9C%8D%E6%8F%90%E7%A4%BA%E4%BF%A1%E6%81%AF.html`

## 验收

开启后只隐藏掉落提示；关闭后恢复。两种状态下掉落物、拾取、首爆和回收结果均不得变化。
