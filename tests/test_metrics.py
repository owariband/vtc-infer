from prometheus_client import CollectorRegistry, generate_latest

from tinyinfer.scheduler.vtc import VTCState
from tinyinfer.telemetry.metrics import SchedulerMetrics


def test_scheduler_metrics_have_only_bounded_labels(monkeypatch) -> None:
    monkeypatch.setenv("VTC_INFER_VERSION", "0.2.0")
    monkeypatch.setenv("VTC_INFER_GIT_SHA", "abc123")
    registry = CollectorRegistry()
    metrics = SchedulerMetrics(registry)
    state = VTCState()
    state.enqueue("request-1", "secret-tenant", input_tokens=4)

    metrics.mark_build()
    metrics.record_decision()
    metrics.observe_selection(0.001)
    metrics.observe_state(state)

    rendered = generate_latest(registry).decode()
    assert 'policy="vtc"' in rendered
    assert 'reason="minimum_effective_counter"' in rendered
    assert 'version="0.2.0"' in rendered
    assert 'git_sha="abc123"' in rendered
    assert "secret-tenant" not in rendered
    assert "request-1" not in rendered
