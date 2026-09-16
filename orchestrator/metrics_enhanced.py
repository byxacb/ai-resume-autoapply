"""增强版监控指标 + 告警规则

扩展原有 metrics：
- 增加 LLM 错误计数、HTTP 错误计数
- 增加耗时告警（>30s warn, >60s error）
- 提供告警事件接口，供 WebSocket 推送
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .metrics import Counter, Gauge, Histogram

logger = __import__('logging').getLogger(__name__)


@dataclass
class AlertEvent:
    ts: float = field(default_factory=time.time)
    level: str = 'warn'
    metric: str = ''
    message: str = ''
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self):
        return {
            'ts': self.ts,
            'level': self.level,
            'metric': self.metric,
            'message': self.message,
            'labels': self.labels,
        }


class AlertRegistry:
    def __init__(self):
        self._alerts: List[AlertEvent] = []
        self._limit = 200

    def record(self, level: str, metric: str, message: str, labels: Dict[str, str] | None = None):
        ev = AlertEvent(level=level, metric=metric, message=message, labels=labels or {})
        self._alerts.append(ev)
        if len(self._alerts) > self._limit:
            self._alerts = self._alerts[-self._limit :]
        logger.warning('ALERT %s %s %s', level, metric, message)

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        items = self._alerts[-limit:]
        return [x.to_dict() for x in items]


# 全局增强指标
LLM_ERRORS = Counter('ai_resume_llm_errors_total', 'LLM error count', labelnames=('provider',))
HTTP_ERRORS = Counter('ai_resume_http_errors_total', 'HTTP error count', labelnames=('status',))
REQUEST_DURATION = Histogram(
    'ai_resume_request_duration_seconds',
    'Request duration seconds',
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600],
)

alerts = AlertRegistry()


def observe_request_duration(seconds: float, endpoint: str = ''):
    REQUEST_DURATION.observe(seconds, endpoint)
    if seconds > 60:
        alerts.record('error', 'request_duration', f'{endpoint} took {seconds:.1f}s', {'endpoint': endpoint})
    elif seconds > 30:
        alerts.record('warn', 'request_duration', f'{endpoint} took {seconds:.1f}s', {'endpoint': endpoint})


def record_llm_error(provider: str = 'unknown'):
    LLM_ERRORS.labels(provider=provider).inc()
    alerts.record('error', 'llm_error', f'llm error from {provider}', {'provider': provider})


def record_http_error(status: str = '500'):
    HTTP_ERRORS.labels(status=status).inc()
    alerts.record('warn', 'http_error', f'http {status}', {'status': status})
