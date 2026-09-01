# 详细整合方案

## 1. 数据流

```
用户上传 master 简历（PDF/DOCX）
        ↓
Resume-Matcher /api/v1/resumes/upload
        ↓
返回 resume_id（存入 SQLite + uploads/）
        ↓
用户输入搜索关键词（如 "iOS 深圳"）
        ↓
auto_job 的 finding_jobs.py 用 Selenium 抓 BOSS
        ↓
对每个 JD：
        ↓
Resume-Matcher /api/v1/jobs/upload （JD 文本入库）
        ↓
Resume-Matcher /api/v1/resumes/improve/preview （触发 LLM 评分 + diff 改写）
        ↓
返回 ATS 评分 + preview_hash + 改进后的简历
        ↓
Orchestrator 判断 score >= 60 ?
        ↓
  是 → /api/v1/resumes/improve/confirm + /cover-letter
        ↓
       auto_job.write_response.py 用 Selenium 粘贴求职信到 BOSS 聊天框
        ↓
       记录到 ApplyRecord
        ↓
  否 → 跳过，记入 skipped 统计
```

## 2. Resume-Matcher 关键内部流程

当 `POST /improve/preview` 被调用时：

1. `improver.py:extract_job_keywords()` — LLM 抽取 JD 关键词（缓存到 job 的 content_hash）
2. `improver.py:generate_skill_target_plan()` — 规划要新增的技能
3. `improver.py:generate_resume_diffs()` — LLM 生成 diff 操作
4. `improver.py:apply_diffs()` — 应用 diff（路径白名单 + 块前缀验证）
5. `improver.py:verify_diff_result()` — 验证改写结果
6. `refiner.py:refine_resume()` — 多 pass 润色
7. `ats.py:compute_ats_score()` — 计算 ATS 评分
8. `refiner.py` 还会做：AI 词黑名单替换、master 简历对齐校验

整个流程在 `asyncio.wait_for(240s)` 内完成。

## 3. auto_job 关键内部流程

主入口 `write_response.py:135 send_job_descriptions_to_chat()`：

1. `finding_jobs.open_browser_with_options()` — 启动 Selenium Chrome
2. `finding_jobs.log_in()` — 点击登录 → 微信扫码（人工一次性）
3. `finding_jobs.select_dropdown_option()` — 选择职位类别
4. `finding_jobs.get_job_description_by_index(i)` — 抓第 i 个职位的 JD
5. 检查按钮是 "立即沟通" 还是 "继续沟通"（已沟通过的跳过）
6. `chat(jd, assistant_id)` 或 `generate_letter(vectorstore, jd)` — 生成求职信
7. 点击 "立即沟通" → 打开聊天窗口
8. `send_response_to_chat_box()` — 粘贴求职信 → 按回车发送

## 4. 整合层要做的改造

### 改造 1: auto_job 的 prompt（去掉硬编码）

原 `prompts.py`：
```python
assistant_instructions = """
    本助手将扮演一位求职者的角色，...
    结尾是真诚的，付尧全。
"""
```

改造后（在 orchestrator 这一层）：
```python
prompt_template = """
    你正在为 {candidate_name}（{candidate_title}）撰写求职信。

    简历核心优势：{matched_keywords}
    匹配度评分：{ats_score}/100
    缺失技能：{missing_keywords}

    工作描述：{jd_text}

    要求：
    - 字数严格 < 300 字
    - 中文
    - 开头"招聘负责人"
    - 结尾"{candidate_name}"
    - 不要包含求职信外的内容
    - 强调与 JD 匹配的技能
"""
```

### 改造 2: auto_job 不用 OpenAI Assistant API

原 `functions.py` 用了 `openai.beta.assistants.create()`，这是 OpenAI 已弃用的 API。

改造后：
```python
# 删除 functions.py
# 改为调用 Resume-Matcher 的 /cover-letter API
cover_letter = await matcher.generate_cover_letter(resume_id, job_id)
```

或者，如果不想走 HTTP，直接 import Resume-Matcher 的 `app/services/cover_letter.py:generate_cover_letter()`，配合 `app/llm.py`。

### 改造 3: 加匹配度过滤

在 `write_response.py:141` 的循环里加：
```python
# 在调用 chat() 前
preview = await matcher.improve_preview(resume_id, job_id)
scores = extract_match_score(preview)
if scores['overall_score'] < MIN_MATCH_SCORE:
    print(f"⏭️ Skipped: {scores['overall_score']} < {MIN_MATCH_SCORE}")
    continue
```

### 改造 4: 持久化投递记录

新建 SQLite 表 `applications`（已有 schema，参考 `apps/backend/app/schemas/applications.py`）：
- job_id
- company
- title
- applied_at
- ats_score
- cover_letter_text
- status (sent/failed/skipped)

## 5. BOSS 直聘对接的坑

详见 `BOSS_RPA_NOTES.md`：
- 微信扫码登录有效期 7 天
- Selenium 直接用会被检测 → 用 undetected-chromedriver
- BOSS 限流：每小时最多 ~30 次打招呼（新号更严）
- 必须用真人行为：随机间隔、偶尔鼠标移动、不连续点击

## 6. LLM 选型建议

按成本/效果排序：

| LLM | 成本（每 1M token） | 中文 | 长 JD 处理 | 推荐度 |
|-----|------------------|------|-----------|-------|
| DeepSeek-V3 | ¥1-2 | ⭐⭐⭐⭐⭐ | 64K context | ⭐⭐⭐⭐⭐ |
| Kimi (Moonshot) | ¥12-60 | ⭐⭐⭐⭐⭐ | 128K context | ⭐⭐⭐⭐ |
| GLM-4 | ¥5-50 | ⭐⭐⭐⭐ | 128K context | ⭐⭐⭐⭐ |
| Qwen3-Max | ¥2-20 | ⭐⭐⭐⭐⭐ | 32K context | ⭐⭐⭐⭐ |
| GPT-4o | $2.5-10 | ⭐⭐⭐ | 128K context | ⭐⭐⭐ |
| Claude Sonnet | $3-15 | ⭐��⭐ | 200K context | ⭐⭐⭐ |

**首选 DeepSeek**：成本最低，中文最好，长 JD 处理足够。

## 7. 部署建议

### 最简部署（单机）
```bash
# 1. 启动 Resume-Matcher 后端
cd Resume-Matcher/apps/backend
uv run uvicorn app.main:app --reload --port 8000

# 2. 启动 orchestrator（CLI 模式）
cd ai-resume-autoapply
python -m orchestrator.run --resume ./master.pdf --jd-file ./jds.json
```

### 进阶部署（Web UI + Redis 队列）
```
Resume-Matcher (FastAPI :8000)
       ↓ REST
Orchestrator (FastAPI :8080)
       ↓ Redis Queue
Auto-job worker (Selenium) × N 个并发
       ↓
BOSS 直聘
```

## 8. 测试策略

### 单元测试
- `matcher_client.py` 用 respx mock HTTP
- `applier_client.py` 用 unittest.mock mock subprocess

### 集成测试
- 用 httpx ASGITransport 测 Resume-Matcher
- 用 pytest-playwright 测 BOSS RPA

### 端到端测试
- 准备 10 个真实 JD（手动标注匹配度）
- 跑 orchestrator，验证：
  - 低分 JD 被跳过
  - 高分 JD 真的被打招呼（人工验证聊天记录）

## 9. 进阶功能（待实现）

- [ ] 支持拉勾网、猎聘、智联
- [ ] 投递后追踪（HR 是否已读、是否回复）
- [ ] 自动跟投：HR 没回，3 天后再发一次
- [ ] 投递日报：每天自动生成"投了 30 家，3 家回复"的统计
- [ ] 多账号轮询
- [ ] Web UI（拖拽上传简历、可视化评分雷达图）
