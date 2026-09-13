"""Low-cardinality Prometheus metrics for the VTC scheduler."""

from __future__ import annotations

import os
from typing import Any

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram


class SchedulerMetrics:
    """Metrics owned by one EngineCore process.

    Tenant and request identifiers are deliberately excluded from labels.
    """

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.decisions = Counter(
            "vtc_infer_scheduler_decisions_total",
            "Number of scheduler admission decisions.",
            ("policy", "reason"),
            registry=registry,
        )
        self.selection_seconds = Histogram(
            "vtc_infer_scheduler_selection_seconds",
            "Time spent selecting one request from the VTC waiting queue.",
            ("policy",),
            registry=registry,
        )
        self.active_tenants = Gauge(
            "vtc_infer_active_tenants",
            "Number of tenants with an outstanding request.",
            ("policy",),
            registry=registry,
            multiprocess_mode="livemax",
        )
        self.service_gap = Gauge(
            "vtc_infer_service_gap",
            "Maximum effective-counter gap among active tenants.",
            ("policy",),
            registry=registry,
            multiprocess_mode="livemax",
        )
        self.build_info = Gauge(
            "vtc_infer_build_info",
            "VTC-Infer build identity.",
            ("version", "git_sha"),
            registry=registry,
            multiprocess_mode="max",
        )

    def mark_build(self) -> None:
        self.build_info.labels(
            version=os.getenv("VTC_INFER_VERSION", "unknown"),
            git_sha=os.getenv("VTC_INFER_GIT_SHA", "unknown"),
        ).set(1)

    def observe_selection(self, seconds: float) -> None:
        self.selection_seconds.labels(policy="vtc").observe(seconds)

    def record_decision(self) -> None:
        self.decisions.labels(
            policy="vtc", reason="minimum_effective_counter"
        ).inc()

    def observe_state(self, state: Any) -> None:
        self.active_tenants.labels(policy="vtc").set(state.active_tenant_count)
        self.service_gap.labels(policy="vtc").set(state.active_service_gap)


_scheduler_metrics: SchedulerMetrics | None = None


def scheduler_metrics() -> SchedulerMetrics:
    global _scheduler_metrics
    if _scheduler_metrics is None:
        _scheduler_metrics = SchedulerMetrics()
    return _scheduler_metrics
