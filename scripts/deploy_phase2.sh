#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]] || [[ "$1" != "fcfs" && "$1" != "vtc" && "$1" != "invalid-scheduler" ]]; then
  echo "usage: $0 <fcfs|vtc|invalid-scheduler>" >&2
  exit 2
fi

policy=$1
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
values_file="$repo_root/deploy/production-stack/values-${policy}.yaml"

: "${VTC_IMAGE_REPOSITORY:?set the engine image repository}"
: "${VTC_IMAGE_TAG:?set immutable-tag@sha256:digest}"
: "${VTC_ROUTER_REPOSITORY:?set the router image repository}"
: "${VTC_ROUTER_TAG:?set v0.1.12@sha256:digest}"

digest_pattern='@sha256:[0-9a-f]{64}$'
if [[ ! "$VTC_IMAGE_TAG" =~ $digest_pattern ]]; then
  echo "VTC_IMAGE_TAG must end in @sha256:<64 lowercase hex characters>" >&2
  exit 2
fi
if [[ ! "$VTC_ROUTER_TAG" =~ $digest_pattern ]]; then
  echo "VTC_ROUTER_TAG must end in @sha256:<64 lowercase hex characters>" >&2
  exit 2
fi

runtime_class=${VTC_RUNTIME_CLASS:-nvidia}
helm_args=(
  upgrade --install vtc-infer vllm/vllm-stack
  --version 0.1.12
  --namespace vtc-infer
  --create-namespace
  --timeout 30m
  --values "$values_file"
  --set-string "servingEngineSpec.runtimeClassName=${runtime_class}"
  --set-string "servingEngineSpec.modelSpec[0].runtimeClassName=${runtime_class}"
  --set-string "servingEngineSpec.modelSpec[0].repository=${VTC_IMAGE_REPOSITORY}"
  --set-string "servingEngineSpec.modelSpec[0].tag=${VTC_IMAGE_TAG}"
  --set-string "servingEngineSpec.modelSpec[0].initContainer.image=${VTC_IMAGE_REPOSITORY}:${VTC_IMAGE_TAG}"
  --set-string "routerSpec.repository=${VTC_ROUTER_REPOSITORY}"
  --set-string "routerSpec.tag=${VTC_ROUTER_TAG}"
)

if [[ "$policy" == "invalid-scheduler" ]]; then
  helm "${helm_args[@]}" --wait
else
  helm "${helm_args[@]}" --atomic
  kubectl apply -f "$repo_root/deploy/monitoring/prometheus-rules.yaml"
  kubectl -n vtc-infer create configmap vtc-infer-dashboard \
    --from-file=vtc-infer-overview.json="$repo_root/dashboards/vtc-infer-overview.json" \
    --dry-run=client -o yaml \
    | kubectl label --local -f - grafana_dashboard=1 -o yaml \
    | kubectl apply -f -
fi
