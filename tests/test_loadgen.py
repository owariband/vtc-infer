from dataclasses import replace

from benchmark.loadgen import generate_schedule
from benchmark.schema import TenantConfig, WorkloadConfig


def _config() -> WorkloadConfig:
    return WorkloadConfig(
        name="test",
        duration_seconds=10,
        seed=42,
        model="model",
        endpoint="http://localhost/v1/chat/completions",
        tenants=(
            TenantConfig("a", 2.0, 16, 8),
            TenantConfig("b", 1.0, 16, 8),
        ),
    )


def test_schedule_is_repeatable_and_sorted() -> None:
    first = generate_schedule(_config())
    second = generate_schedule(_config())
    assert first == second
    assert first == sorted(first, key=lambda item: (item.scheduled_time, item.request_id))
    assert all(item.scheduled_time <= 10 for item in first)


def test_seed_changes_schedule() -> None:
    config = _config()
    assert generate_schedule(config) != generate_schedule(replace(config, seed=43))
