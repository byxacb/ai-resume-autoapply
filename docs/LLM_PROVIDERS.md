# LLM 提供商配置指南

## 推荐：DeepSeek（成本最低 + 中文最好）

### 获取 API Key
1. 访问 https://platform.deepseek.com
2. 注册 → API Keys → Create new secret key
3. 充值 ¥10（够用很久）

### 配置 .env
在 `Resume-Matcher/apps/backend/.env`：
```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-deepseek-key
LLM_MODEL=deepseek-chat
```

### 成本估算
- deepseek-chat：¥1/1M input tokens，¥2/1M output tokens
- 每次"上传简历 + 评分 + 改写 + 求职信"：约 5000 input + 2000 output tokens
- 成本：~¥0.01 / 次
- 100 个职位投递：~¥1

## 备选：Kimi（128K context）

适合 JD 极长的场景。

```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-kimi-key
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-128k
```

## 备选：GLM-4（智谱）

适合企业用户。

```bash
LLM_PROVIDER=openai
LLM_API_KEY=your-glm-key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4-plus
```

## 本地：Ollama（零成本但慢）

适合隐私优先用户。

```bash
# 1. 安装 ollama
brew install ollama
ollama serve

# 2. 拉模型
ollama pull qwen2.5:14b  # 推荐，中文好

# 3. 配置
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:14b
```

注意：本地模型对评分准确性略差，但完全免费且隐私。

## 备选：OpenAI（兼容性最好）

```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```
