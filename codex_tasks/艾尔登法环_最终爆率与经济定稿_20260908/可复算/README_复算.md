# 数值复算
运行环境：Python 3，numpy、scipy、pytest。
在本目录执行：
```
python -m pytest -q engine/test_drop_math.py
python engine/build_rates.py
```
程序只读取engine/inputs.json，并写入本目录output；不访问服务器或GitHub。
inputs.json为上一批“爆率前设计定稿”的实际冻结输入。输出包含5351触发、46组取得时间、资源预算、回刷及敏感性结果。
此次计算运行两次，output/results.json的SHA256一致；交付XLSX根据同一结果制作并逐格对照。重新导出XLSX可能改变内部文件元数据，不要求其ZIP字节不变。
物品数量、币种单位和先留用后回收的规则在build_rates.py中明示；不把技能×2再次乘在输入TTK上。
主线概率模型为p=min(1,人物有效爆率/基础分母)。鞭尸按概率w增加一次独立判定，期望乘1+w；此模型需与现服语义核对，不直接写脚本增加第二次鞭尸。
逐件取得85%储备是预算约束，并非全部物品联合85%保证；阶段表另给指定装备凑齐的长尾参考。资源预算不是固定通关时间。
