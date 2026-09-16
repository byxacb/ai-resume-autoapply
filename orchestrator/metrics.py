"""Prometheus-style metrics (no external dep required).

We avoid the prometheus_client package to keep deps minimal; instead we
expose a tiny in-process registry compatible with the Prometheus text
exposition format. If you want richer features (multi-process mode,
pushgateway, etc.) just swap render() with prometheus_client.generate_latest().
"""
from typing import Dict, List, Optional, Tuple


class Counter:
    """Counter metric supporting labels."""

    def __init__(self, name: str, help_text: str, labelnames: Tuple[str, ...] = ()):
        self.name = name
        self.help = help_text
        self.labelnames = labelnames
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = {}

    def labels(self, **kwargs) -> "_CounterChild":
        key = tuple(sorted(kwargs.items()))
        return _CounterChild(self, key)

    def inc(self, amount: float = 1.0) -> None:
        self._values[()] = self._values.get((), 0.0) + amount

    def render(self) -> str:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        if not self.labelnames:
            out.append(f"{self.name} {self._values.get((), 0)}")
        else:
            for labels, val in self._values.items():
                label_str = ",".join(f'{k}="{v}"' for k, v in labels)
                out.append(f"{self.name}{{{label_str}}} {val}")
        return "\n".join(out)


class _CounterChild:
    def __init__(self, parent: Counter, key):
        self.parent = parent
        self.key = key

    def inc(self, amount: float = 1.0) -> None:
        self.parent._values[self.key] = self.parent._values.get(self.key, 0.0) + amount


class Gauge:
    """Gauge metric (single value, can go up/down)."""

    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help = help_text
        self.value = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        self.value -= amount

    def set(self, value: float) -> None:
        self.value = value

    def render(self) -> str:
        return f"# HELP {self.name} {self.help}\n# TYPE {self.name} gauge\n{self.name} {self.value}"


class Histogram:
    """Histogram metric (cumulative buckets, sum, count)."""

    def __init__(
        self,
        name: str,
        help_text: str,
        buckets: Optional[List[float]] = None,
    ):
        self.name = name
        self.help = help_text
        self.buckets = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, float("inf")]
        self.count = 0
        self.sum = 0.0
        self.bucket_counts: Dict[float, int] = {b: 0 for b in self.buckets}

    def observe(self, value: float) -> None:
        self.count += 1
        self.sum += value
        for b in self.buckets:
            if value <= b:
                self.bucket_counts[b] += 1

    def render(self) -> str:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for b in self.buckets:
            label = "+Inf" if b == float("inf") else str(b)
            out.append(self.name + '_bucket{le="' + label + '"} ' + str(self.bucket_counts[b]))
        out.append(f"{self.name}_sum {self.sum}")
        out.append(f"{self.name}_count {self.count}")
        return "\n".join(out)


# === Global metric registry ===

JOBS_PROCESSED = Counter(
    "ai_resume_jobs_processed_total",
    "Total jobs processed by orchestrator",
    labelnames=("result",),
)
RUNS_TOTAL = Counter(
    "ai_resume_runs_total",
    "Total orchestrator runs",
    labelnames=("status",),
)
CANDIDATES_TOTAL = Counter(
    "ai_resume_candidates_total",
    "Total candidates registered",
)
INFLIGHT_RUNS = Gauge(
    "ai_resume_inflight_runs",
    "Number of currently running orchestrator tasks",
)
ATS_SCORE = Histogram(
    "ai_resume_ats_score",
    "Distribution of ATS scores",
    buckets=[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
)
RUN_DURATION = Histogram(
    "ai_resume_run_duration_seconds",
    "Time taken to complete a run",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
)
QUEUE_SIZE = Gauge(
    "ai_resume_queue_size",
    "Current Redis queue size",
)
LLM_TOKENS = Counter(
    "ai_resume_llm_tokens_total",
    "LLM tokens consumed",
    labelnames=("model", "kind"),
)


def render() -> str:
    parts = [
        JOBS_PROCESSED.render(),
        RUNS_TOTAL.render(),
        CANDIDATES_TOTAL.render(),
        INFLIGHT_RUNS.render(),
        ATS_SCORE.render(),
        RUN_DURATION.render(),
        QUEUE_SIZE.render(),
        LLM_TOKENS.render(),
    ]
    return "\n".join(parts)
