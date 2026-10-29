# 原版 WZL / PAK 适配器

`adapter=resource` 直接复用 `E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeResourceTool\XuanYuanNativeResourceTool.exe`。它有独立的发布 manifest；本次不重编、不复制其资源操作实现。

调用前按需读取 `E:\XuanYuanDevPlatform\wzl编辑\docs\native-resource-tool.md`。请求原样转发，支持 `import`、`batch-import`、`export`、`batch-export`。

单图导出示例：

```json
{
  "schemaVersion": 1,
  "requestId": "export-one",
  "command": "export",
  "arguments": {
    "source": "D:\\资源输入\\example.wzl",
    "outputRoot": "D:\\codex临时工作区\\资源任务\\export-one",
    "id": 0,
    "format": "PNG"
  },
  "policy": {
    "allowedWriteRoots": ["D:\\codex临时工作区\\资源任务"]
  }
}
```

outputRoot 必须尚不存在。WZL 要有同名 WZX；原版编辑器在任务副本导入/导出并回读。批量导出用 startId/endId，导入用 image 或 images 以及 mode=append/replace。

PAK 使用 `passwordRef` 指向用户明确提供的 gui-config 节；密码不写入请求、截图说明或日志。不要把请求全文作为错误日志回显。实际工具只在进程中读取密码并交原版处理。

成功应检查 `backendResponse.ok`、源保护、输出资源/图片/坐标回读与哈希，不以鼠标点击完成作为导出成功。候选产物部署和客户端游戏内验收单独执行。
