import pytest

from analysis.report import jain_index, percentile, summarize


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([], 0.5) is None


def test_jain_index_for_equal_service() -> None:
    assert jain_index([10, 10]) == 1.0


def test_summarize_groups_tenant_ttft_and_throughput() -> None:
    summary = summarize(
        [
            {
                "tenant_id": "a",
                "status": "ok",
                "arrival_time": 0.0,
                "first_token_time": 1.0,
                "end_time": 2.0,
                "prompt_tokens": 10,
                "output_tokens": 10,
            },
            {
                "tenant_id": "b",
                "status": "ok",
                "arrival_time": 1.0,
                "first_token_time": 3.0,
                "end_time": 4.0,
                "prompt_tokens": 10,
                "output_tokens": 10,
            },
        ]
    )
    assert summary["tenants"]["a"]["ttft_seconds"]["p95"] == 1.0
    assert summary["tenants"]["b"]["ttft_seconds"]["p95"] == 2.0
    assert summary["output_throughput_tokens_per_second"] == pytest.approx(5.0)
    assert summary["jain_service_index"] == 1.0
