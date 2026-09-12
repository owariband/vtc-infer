"""Validated data contracts shared by the load generator and analysis tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


def _positive(name: str, value: float | int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True)
class TenantConfig:
    tenant_id: str
    request_rate: float
    prompt_tokens: int
    max_output_tokens: int
    system_prompt: str = ""
    prompt_prefix: str = ""

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        _positive("request_rate", self.request_rate)
        _positive("prompt_tokens", self.prompt_tokens)
        _positive("max_output_tokens", self.max_output_tokens)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TenantConfig":
        return cls(**dict(value))


@dataclass(frozen=True)
class WorkloadConfig:
    name: str
    duration_seconds: float
    seed: int
    model: str
    endpoint: str
    tenants: tuple[TenantConfig, ...]
    request_timeout_seconds: float = 300.0
    max_in_flight: int = 512

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("workload name must not be empty")
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an HTTP(S) URL")
        _positive("duration_seconds", self.duration_seconds)
        _positive("request_timeout_seconds", self.request_timeout_seconds)
        _positive("max_in_flight", self.max_in_flight)
        if not self.tenants:
            raise ValueError("at least one tenant is required")
        tenant_ids = [tenant.tenant_id for tenant in self.tenants]
        if len(tenant_ids) != len(set(tenant_ids)):
            raise ValueError("tenant_id values must be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkloadConfig":
        data = dict(value)
        data["tenants"] = tuple(
            TenantConfig.from_mapping(tenant) for tenant in data.get("tenants", ())
        )
        return cls(**data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WorkloadConfig":
        with Path(path).open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        if not isinstance(value, Mapping):
            raise ValueError("workload YAML must contain a mapping")
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequestRecord:
    experiment_id: str
    request_id: str
    tenant_id: str
    policy: str
    scheduled_time: float
    arrival_time: float | None = None
    first_token_time: float | None = None
    end_time: float | None = None
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    status: str = "scheduled"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentManifest:
    experiment_id: str
    policy: str
    started_at: str
    git_commit: str
    workload: dict[str, Any]
    git_dirty: bool = False
    service_parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
