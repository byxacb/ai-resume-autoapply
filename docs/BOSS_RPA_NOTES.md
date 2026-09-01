# BOSS 直聘 RPA 风控笔记

## 1. 登录方式

BOSS 直聘**不支持**账号密码登录，只支持：
- 微信扫码
- 手机验证码
- 二维码（App 扫）

`auto_job/finding_jobs.py:45-69` 走的是微信扫码路径：
```python
# 点击登录
login_button = driver.find_element(By.XPATH, "//*[@id='header']/div[1]/div[3]/div/a")
login_button.click()

# 点击微信登录
wechat_button = driver.find_element(By.XPATH, ".../div[4]/a")
wechat_button.click()

# 等待扫码（60s）
WebDriverWait(driver, 60).until(
    EC.presence_of_element_located((By.XPATH, ".../li[2]/a"))
)
```

**有效期**：扫码登录的 session 通常能保持 7-30 天。

## 2. 风控规则（实测）

### 频率限制
| 行为 | 阈值 | 后果 |
|------|------|------|
| 单个 HR 打招呼 | 1 次 | 第 2 次会被拒 |
| 每小时打招呼 | ~30 次（新号） / ~100 次（老号） | 触发滑块验证码 |
| 每天打招呼 | ~200 次 | 账号被临时限制 |
| 同公司打招呼 | 3-5 次 | 后续打招呼被静音 |

### 行为检测
BOSS 用**网易易盾**做风控，会检测：
- 鼠标轨迹（Selenium 默认轨迹太规律）
- 键盘输入（pyautogui 直接发送会被识别）
- 浏览器指纹（navigator.webdriver = true）
- TLS 指纹

### 触发后果
- 滑块验证码（必须人工过）
- IP 风控（换 IP）
- 账号风控（换号）

## 3. 反检测策略

### 方案 A: undetected-chromedriver（最简单）
```python
import undetected_chromedriver as uc

options = uc.ChromeOptions()
driver = uc.Chrome(options=options)
```

它会自动：
- 移除 navigator.webdriver 标记
- 注入真实 Chrome 指纹
- 处理 TLS 指纹

### 方案 B: stealth + 行为模拟
```python
from selenium_stealth import stealth

stealth(driver,
    languages=["zh-CN", "zh", "en"],
    vendor="Google Inc.",
    platform="Win32",
    webgl_vendor="Intel Inc.",
    renderer="Intel Iris OpenGL Engine",
    fix_hairline=True,
)
```

外加行为模拟：
```python
import pyautogui
import random

# 模拟真人鼠标移动
def human_like_click(driver, element):
    box = element.location_once_scrolled_into_view
    start_x, start_y = pyautogui.position()
    target_x = box['x'] + random.randint(5, 20)
    target_y = box['y'] + random.randint(5, 20)
    pyautogui.moveTo(target_x, target_y, duration=random.uniform(0.5, 1.5))
    element.click()
```

### 方案 C: 真人浏览器 + 远程调试
- 自己打开 Chrome，登录 BOSS
- 用 `chrome --remote-debugging-port=9222` 暴露 CDP
- Selenium 通过 CDP 连接

**优点**：100% 真人浏览器
**缺点**：每次要人工启动

## 4. 推荐方案

**MVP 用 undetected-chromedriver**，**生产用真人浏览器+远程调试**。

```python
# 推荐做法
from auto_job.finding_jobs import get_driver, log_in, select_dropdown_option

# 1. 启动 undetected Chrome
import undetected_chromedriver as uc
driver = uc.Chrome(version_main=142)
driver.maximize_window()

# 2. 打开 BOSS
driver.get("https://www.zhipin.com/web/geek/job-recommend")

# 3. 人工扫码登录（一次性）
WebDriverWait(driver, 60).until(
    EC.presence_of_element_located((By.XPATH, "//*[@id='header']/div[1]/div[3]/ul/li[2]/a"))
)

# 4. 后续 RPA 复用这个 driver
```

## 5. 频率控制参考实现

```python
import random
import time
from datetime import datetime, timedelta

class BossRateLimiter:
    def __init__(self):
        self.actions = []
        self.company_count = {}

    def can_apply(self, company: str) -> bool:
        now = datetime.now()
        # 清空 1 小时前的记录
        self.actions = [t for t in self.actions if now - t < timedelta(hours=1)]

        if len(self.actions) >= 25:
            return False
        if self.company_count.get(company, 0) >= 3:
            return False
        return True

    def record(self, company: str):
        self.actions.append(datetime.now())
        self.company_count[company] = self.company_count.get(company, 0) + 1

    def wait(self):
        # 基础 30s + 随机 0-30s 抖动
        wait = 30 + random.uniform(0, 30)
        time.sleep(wait)
```

## 6. 失败重试策略

| 错误类型 | 重试策略 |
|---------|---------|
| 滑块验证码 | 不重试，人工介入 |
| 找不到元素（XPath 变了） | 重试 3 次，每次间隔 5s |
| 网络超时 | 重试 3 次，指数退避 |
| 已被风控 | 暂停 30 分钟，之后重试 |

## 7. 数据持久化

建议投递记录用 SQLite 存：

```sql
CREATE TABLE applications (
    id INTEGER PRIMARY KEY,
    job_id TEXT,
    company TEXT,
    title TEXT,
    applied_at TIMESTAMP,
    ats_score REAL,
    cover_letter TEXT,
    status TEXT,  -- sent/failed/skipped/rate_limited
    error TEXT,
    hr_read_at TIMESTAMP,
    hr_replied_at TIMESTAMP
);
```

## 8. 法律风险

⚠️ **重要提醒**：
1. BOSS 直聘用户协议可能禁止自动化操作
2. 海投可能伤害你的职业形象（HR 一眼看出是机器人发的）
3. 频繁打招呼会被 HR 拉黑

**建议**：
- 每天最多 30-50 次（不要 200+）
- 求职信要有针对性，不要千篇一律
- 手动 + 自动结合：自动投低优先级职位，手动投心仪公司
