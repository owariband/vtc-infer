#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]] || [[ ! "$1" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <healthy-revision-number>" >&2
  exit 2
fi

revision=$1
helm -n vtc-infer rollback vtc-infer "$revision" \
  --wait --timeout 30m --cleanup-on-fail

engine_deployment=$(kubectl -n vtc-infer get deployment \
  -l app.kubernetes.io/component=serving-engine \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n vtc-infer rollout status "deployment/${engine_deployment}" --timeout=30m
