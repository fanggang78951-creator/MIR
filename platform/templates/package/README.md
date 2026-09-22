# 新成果包模板

复制本目录到 `packages\candidate\xy.你的包ID`，填写清单和 payload，运行：

```powershell
bin\xydp-cli.exe list-packages
python -m unittest discover -s tests -v
```

通过静态和游戏验证后才能把状态改为 `verified`。
