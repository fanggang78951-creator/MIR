# 地图0狂暴NPC唯一业务源静态证据

- 唯一业务文件：`QuestDiary/玄渊功能/狂暴/狂暴NPC接口.txt`。
- 地图0物理NPC、`@XY_RAGE_COMMAND` 与左上狂暴图标共同调用 `@XY_RAGE_NPC_MAIN`。
- 是否开启只认 `CHECKFENGHAO 狂暴之力`，不再使用 `N$XY_RAGE_ACTIVE` 或独立 `POWERRATE` 后台状态。
- 费用不足分支不会授予称号，也不会触发彩色图标刷新。
- 狂暴称号属性出口沿用原 `xy.ops.rage-title` 已施工逻辑：称号物品、爆率锚点、死亡回收与击杀奖励。
- `狂暴界面刷新接口.txt` 由 `ensure_event_label` 创建安全空事件桩；属性图标包通过受管事件钩子追加即时刷新。以后单独预检或升级狂暴包会原样保留该钩子，不复制任何狂暴业务。
- 正式端迁移前必须识别并移除旧 `xy.optional.rage.core` 的 AttackDamage/PlayOffLine 后台钩子和旧核心、配置文件，发现手工修改时阻止。
