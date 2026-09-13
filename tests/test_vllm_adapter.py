import pytest

pytest.importorskip("vllm")

from vllm.v1.core.sched.async_scheduler import AsyncScheduler

from tinyinfer.scheduler.vllm_adapter import (
    CustomAsyncFCFSScheduler,
    VTCScheduler,
)


def test_custom_async_fcfs_keeps_upstream_scheduling_policy():
    assert issubclass(CustomAsyncFCFSScheduler, AsyncScheduler)
    assert "schedule" not in CustomAsyncFCFSScheduler.__dict__
    assert "update_from_output" not in CustomAsyncFCFSScheduler.__dict__


def test_vtc_uses_async_scheduler():
    assert issubclass(VTCScheduler, AsyncScheduler)
