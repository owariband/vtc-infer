#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
evidence_dir=${1:-"$repo_root/results/remote/phase2-smoke"}
model=${VTC_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}
mkdir -p "$evidence_dir"

kubectl -n vtc-infer port-forward svc/vtc-infer-router-service 30080:80 \
  >"$evidence_dir/port-forward.log" 2>&1 &
port_forward_pid=$!
trap 'kill "$port_forward_pid" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:30080/health >/dev/null; then
    break
  fi
  sleep 1
done

curl --fail --silent http://127.0.0.1:30080/v1/models \
  > "$evidence_dir/models.json"
curl --fail --no-buffer http://127.0.0.1:30080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${model}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: VTC-Infer ready\"}],\"temperature\":0,\"max_tokens\":16,\"stream\":true,\"stream_options\":{\"include_usage\":true},\"vllm_xargs\":{\"tenant_id\":\"phase2-smoke\"}}" \
  > "$evidence_dir/chat.sse"

grep -q '^data: \[DONE\]' "$evidence_dir/chat.sse"
grep -q '"usage"' "$evidence_dir/chat.sse"
