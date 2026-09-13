from __future__ import annotations

import copy
from pathlib import Path

import yaml


VALUES_DIR = Path("deploy/production-stack")


def load_values(policy: str) -> dict:
    return yaml.safe_load((VALUES_DIR / f"values-{policy}.yaml").read_text())


def normalized_policy_values(values: dict) -> dict:
    result = copy.deepcopy(values)
    model = result["servingEngineSpec"]["modelSpec"][0]
    model["vllmConfig"]["extraArgs"] = ["POLICY_ARGS"]
    model["env"] = [
        env for env in model.get("env", []) if env["name"] not in {
            "VTC_INFER_POLICY",
            "TINYINFER_VTC_WP",
            "TINYINFER_VTC_WQ",
        }
    ]
    return result


def test_fcfs_and_vtc_values_only_differ_by_policy() -> None:
    fcfs = load_values("fcfs")
    vtc = load_values("vtc")

    assert normalized_policy_values(fcfs) == normalized_policy_values(vtc)


def test_phase_two_values_pin_single_gpu_and_disable_out_of_scope_features() -> None:
    for policy in ("fcfs", "vtc"):
        values = load_values(policy)
        engine = values["servingEngineSpec"]
        model = engine["modelSpec"][0]
        resources = model["resources"]

        assert "labels" not in engine
        assert engine["strategy"] == {"type": "Recreate"}
        assert model["replicaCount"] == 1
        assert resources["requests"]["nvidia.com/gpu"] == "1"
        assert resources["limits"]["nvidia.com/gpu"] == "1"
        assert model["vllmConfig"].get("v0") != "1"
        assert model["enableLoRA"] is False
        assert model["lmcacheConfig"]["enabled"] is False
        assert model["keda"]["enabled"] is False
        assert values["routerSpec"]["routingLogic"] == "roundrobin"
        assert values["routerSpec"]["autoscaling"]["enabled"] is False
        assert values["routerSpec"]["startupProbe"]["failureThreshold"] >= 12
        assert values["prometheus-adapter"]["enabled"] is False

        monitoring = values["kube-prometheus-stack"]
        assert monitoring["enabled"] is True
        assert monitoring["defaultRules"]["create"] is False
        assert monitoring["alertmanager"]["enabled"] is False
        assert monitoring["kubeStateMetrics"]["enabled"] is False
        assert monitoring["nodeExporter"]["enabled"] is False


def test_deployable_images_must_be_injected_as_immutable_references() -> None:
    for policy in ("fcfs", "vtc", "invalid-scheduler"):
        values = load_values(policy)
        model = values["servingEngineSpec"]["modelSpec"][0]
        assert model["tag"] == "MUST_BE_OVERRIDDEN_WITH_TAG_AND_DIGEST"
        assert values["routerSpec"]["tag"] == (
            "MUST_BE_OVERRIDDEN_WITH_TAG_AND_DIGEST"
        )
