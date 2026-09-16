# 示例数据

本目录提供样例数据，用于快速体验系统。

- `sample_jds.json`：示例 JD 列表
- `sample_candidate.json`：示例候选人

使用方式：
```bash
python -m uvicorn web.server:app --host 0.0.0.0 --port 8080
```

然后在 Dashboard 的「运行任务」里选择「上传 JD 文件」，选择 `sample_jds.json`。
