import pytest

from benchmark.schema import TenantConfig, WorkloadConfig


def test_workload_rejects_duplicate_tenants() -> None:
    tenant = TenantConfig("tenant-a", 1.0, 32, 16)
    with pytest.raises(ValueError, match="unique"):
        WorkloadConfig(
            name="duplicate",
            duration_seconds=1,
            seed=1,
            model="model",
            endpoint="http://localhost:8000/v1/chat/completions",
            tenants=(tenant, tenant),
        )


def test_noisy_neighbor_config_loads() -> None:
    config = WorkloadConfig.from_yaml("benchmark/workloads/noisy_neighbor.yaml")
    assert config.name == "noisy-neighbor"
    assert {tenant.tenant_id for tenant in config.tenants} == {"tenant-a", "tenant-b"}
