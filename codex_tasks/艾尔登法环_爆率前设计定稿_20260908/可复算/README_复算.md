# 冻结输入复算

这些程序不读写GitHub或游戏服务器。默认工作目录是本文件所在目录。

## 数值复算

```bash
python rebuild.py --require-identical
```

该命令依次执行普通装备调整、普通分支取舍、合成比较、粗略战斗重算、最终封装。7份原输入必须保持SHA256不变；最终数值JSON与交付哈希比较。`normalized_current.json`是当前生成输入，`normalized.json`是冻结的上一版本，不能倒置。

## 工作簿重建

环境需已有`artifact_tool`，本包不包含库/字体/安装文件。可在Python中执行：

```python
import export_workbooks as w
w.equipment()
w.combat()
w.growth()
w.drops()
w.fate()
w.save_logs()
```

工作簿为数据视图；当前模型数值来源是`results/design_final.json`，不要反向从旧XLSX缓存拼回人物。

## 导出核验

```bash
python verify_exports.py
```

用标准库ZIP/XML读回XLSX，不依赖Excel。验证2219个公式缓存、817装备、561怪、619图鉴、命格冻结值以及概率空置。

技能2倍与吸血1.3倍为用户明确的粗算参数。命中95%、有效输出时间80%、部分引擎字段换算等继承适配假设，不冒充本机实测。
