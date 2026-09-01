# ai-resume-autoapply

> **中国本土 AI 简历优化 + 自动投递整合项目**
> Fork 自 [srbhr/Resume-Matcher](https://github.com/srbhr/Resume-Matcher)（简历优化） + [Frrrrrrrrank/auto_job__find__chatgpt__rpa](https://github.com/Frrrrrrrrank/auto_job__find__chatgpt__rpa)（BOSS 自动投递）

把两个 GitHub 上 star 最高、最成熟、各自领域最强的项目粘合起来：

| 模块 | 来自 | 提供的能力 |
|------|------|-----------|
| **简历优化** | Resume-Matcher | JD 匹配评分 / 简历 diff 改写 / 多 LLM 兼容 / 真伪守卫 / ATS 评分 / 求职信 |
| **自动投递** | auto_job | BOSS 直聘 RPA / 自动打招呼 / Selenium 自动化 |

---

## 🎯 核心价值

单独用任何一个项目，都有致命缺陷：

| 痛点 | 只用 Resume-Matcher | 只用 auto_job | **整合后** |
|------|-------------------|--------------|-----------|
| 简历定制 | ⭐⭐⭐⭐⭐ | ❌ | ⭐⭐⭐⭐⭐ |
| JD 匹配评分 | ⭐⭐⭐⭐⭐ | ❌ | ⭐⭐⭐⭐⭐ |
| 自动投递 | ❌ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 求职信定制 | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 投递决策 | ❌ | ❌ | ✅ 匹配度过滤 |
| 国产 LLM | ⭐⭐⭐⭐⭐ | ❌（只支持 OpenAI） | ⭐⭐⭐⭐⭐ |

**核心差异化**：**智能投递决策**——不是无脑海投，而是**先匹配评分，只投高匹配度的职位**，大幅提升回复率。

---

## 🏗️ 架构

```
┌──────────────────────────────────────────────────────────┐
│  Frontend: Web UI / CLI / Claude Code Skill               │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 1: 简历优化（来自 Resume-Matcher）                 │
│  • JD 解析 → 必须/加分/软技能                            │
│  • 关键词缺口分析                                         │
│  • ATS 评分（kw 55% + skills 25% + sections 20%）          │
│  • diff-based 简历改写（路径白名单 + 真伪守卫）            │
│  • 多 LLM：DeepSeek/Kimi/GLM/OpenAI/Claude/Gemini/Ollama │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 2: 投递决策（新增 orchestrator）                   │
│  • ATS 评分 < 60 → 跳过（避免低匹配海投）                 │
│  • ATS 评分 60–80 → 自动投递 + 求职信                     │
│  • ATS 评分 > 80 → 优先投递 + 高亮                        │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  Layer 3: 自动投递（来自 auto_job）                       │
│  • Selenium 打开 BOSS 直聘                                │
│  • 搜索目标职位关键词                                     │
│  • 抓 JD → 重新匹配评分                                   │
│  • 生成定制求职信（基于优化后的简历）                      │
│  • 自动打招呼 / 投递                                      │
│  • 频率控制（防封号）                                     │
└──────────────────────────────────────────────────────────┘
```

---

## 📦 已 fork 的源仓库

- https://github.com/byxacb/Resume-Matcher （28k★，Apache 2.0）
- https://github.com/byxacb/auto_job__find__chatgpt__rpa （1.5k★）

两个仓库都已 fork 到你自己的账号下，可以直接基于本地代码改。

---

## 🧠 关键整合点（已读懂两个项目源码后总结）

### Resume-Matcher 提供的核心 API

```
POST /api/v1/resumes/upload          # 上传 PDF/DOCX 简历
POST /api/v1/resumes/improve/preview # 简历改写预览（返回 ATS 评分）
POST /api/v1/resumes/improve/confirm # 确认改写
POST /api/v1/jobs/upload             # 上传 JD（批量）
GET  /api/v1/resumes/{id}/pdf        # 生成 PDF
```

内部关键模块：
- `app/services/ats.py:171 compute_ats_score()` — 评分函数（kw 55% + skills 25% + sections 20%）
- `app/services/improver.py` — diff-based 改写（路径白名单 + 真伪守卫）
- `app/services/refiner.py` — 多 pass 润色（关键词注入 + AI 词黑名单）
- `app/services/cover_letter.py` — 求职信生成
- `app/llm.py` — LiteLLM 包装，已支持 DeepSeek/OpenAI/Claude/Gemini/Ollama

### auto_job 提供的核心模块

- `finding_jobs.py` — Selenium 浏览器自动化（打开 BOSS、登录、翻页、抓 JD）
- `write_response.py:135 send_job_descriptions_to_chat()` — 主循环
- `langchain_functions.py` — 备选 LangChain 版本（兼容自定义 base_url）
- `prompts.py` — 求职信 prompt（硬编码求职者姓名"付尧全"，需要改）

### 整合需要改的地方

| 来源 | 文件 | 改造内容 |
|------|------|---------|
| auto_job | `prompts.py` | 把硬编码的"付尧全"改成从简历读；prompt 加 `{ats_score}` `{matched_keywords}` |
| auto_job | `functions.py` | 不再用 OpenAI Assistant API，改用 Resume-Matcher 的 `app/llm.py` |
| auto_job | `finding_jobs.py` | 加 X-vendor 抽象层，便于未来加拉勾/猎聘 |
| auto_job | `write_response.py:135` | 主循环前调用 Resume-Matcher `/improve/preview`，score < 阈值就 skip |
| Resume-Matcher | `app/services/cover_letter.py` | 加 `{match_score}` 字段，让求职信引用"匹配度 85%" |
| 新增 | `ai-resume-autoapply/orchestrator/run.py` | 串联两个项目 |

---

## 🗓️ MVP 路线图

### Week 1: 简历优化层
- [ ] 跑通 Resume-Matcher 基础流程
- [ ] 验证 DeepSeek API 可用
- [ ] 测试 ATS 评分准确度

### Week 2: 自动投递层
- [ ] 跑通 auto_job 的 BOSS 自动打招呼
- [ ] 改造 LLM 为 DeepSeek
- [ ] 加频率控制（每小时最多 20 次）

### Week 3: 整合层
- [ ] 写 orchestrator，串联简历优化 → 投递决策 → 自动投递
- [ ] 加匹配度过滤（< 60 分不投递）
- [ ] 求职信用优化后的简历数据

### Week 4: 测试 + 防封号
- [ ] 小规模测试（10 个真实职位）
- [ ] 统计回复率
- [ ] 优化风控策略

---

## ⚠️ 已知风险

1. **BOSS 直聘风控**：Selenium 容易被检测，需要加 `stealth` 模式（undetected-chromedriver）
2. **登录稳定性**：WeChat 扫码登录有效期有限，需要定期人工续期
3. **求职信质量**：300 字硬限制（来自 auto_job），可能装不下所有优势
4. **LLM 成本**：即使 DeepSeek，海投大量职位也会消耗 token，需要缓存

---

## 📂 目录结构

```
ai-resume-integration/
├── Resume-Matcher/                # fork 自 byxacb/Resume-Matcher
│   ├── apps/backend/             # FastAPI 后端（核心）
│   ├── apps/frontend/            # Next.js 前端
│   └── ...
├── auto_job/                     # fork 自 byxacb/auto_job__find__chatgpt__rpa
│   └── auto_job_find/
│       ├── finding_jobs.py       # Selenium 浏览器自动化
│       ├── write_response.py     # 主循环
│       ├── prompts.py            # 求职信 prompt
│       └── langchain_functions.py
└── ai-resume-autoapply/          # 本仓库：整合层
    ├── README.md
    ├── orchestrator/
    │   ├── run.py                # 主入口
    │   ├── matcher_client.py     # 调用 Resume-Matcher API
    │   ├── applier_client.py     # 调用 auto_job RPA
    │   └── config.py             # 统一配置
    └── docs/
        ├── INTEGRATION_PLAN.md   # 详细整合方案
        ├── BOSS_RPA_NOTES.md     # BOSS 自动投递风控笔记
        └── LLM_PROVIDERS.md      # LLM 提供商配置指南
```

---

## 🙏 致谢

- [@srbhr](https://github.com/srbhr) — Resume-Matcher，Apache 2.0
- [@Frrrrrrrrank](https://github.com/Frrrrrrrrank) — auto_job（MIT）

---

## ⚖️ License

本仓库代码：MIT
Resume-Matcher 代码：Apache 2.0（保留原 license）
auto_job 代码：保留原作者声明（README 中作者特别声明"不要拿去割韭菜"）
