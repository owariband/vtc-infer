#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <evidence-directory>" >&2
  exit 2
fi

evidence_dir=$1
mkdir -p "$evidence_dir"/{environment,helm,kubernetes,logs}

git rev-parse HEAD > "$evidence_dir/environment/git-sha.txt"
git status --short > "$evidence_dir/environment/git-status.txt"
uname -a > "$evidence_dir/environment/uname.txt"
nvidia-smi > "$evidence_dir/environment/nvidia-smi.txt"
kubectl version -o yaml > "$evidence_dir/environment/kubectl-version.yaml"
helm version > "$evidence_dir/environment/helm-version.txt"

helm -n vtc-infer status vtc-infer > "$evidence_dir/helm/status.txt"
helm -n vtc-infer history vtc-infer -o json > "$evidence_dir/helm/history.json"
helm -n vtc-infer get values vtc-infer --all > "$evidence_dir/helm/values.yaml"

kubectl -n vtc-infer get pods -o json > "$evidence_dir/kubernetes/pods.json"
kubectl -n vtc-infer get deploy,svc,pvc,servicemonitor,prometheusrule -o yaml \
  > "$evidence_dir/kubernetes/resources.yaml"
kubectl -n vtc-infer get events --sort-by=.lastTimestamp \
  > "$evidence_dir/kubernetes/events.txt"
kubectl -n vtc-infer logs -l app.kubernetes.io/component=serving-engine \
  --all-containers --prefix > "$evidence_dir/logs/engine.log" 2>&1 || true
kubectl -n vtc-infer logs -l app.kubernetes.io/component=router \
  --all-containers --prefix > "$evidence_dir/logs/router.log" 2>&1 || true
