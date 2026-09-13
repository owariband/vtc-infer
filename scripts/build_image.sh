#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing to build from a dirty worktree" >&2
  exit 1
fi

: "${VTC_IMAGE_REPOSITORY:?set VTC_IMAGE_REPOSITORY, for example localhost:5000/vtc-infer-vllm}"
VTC_INFER_VERSION=${VTC_INFER_VERSION:-0.2.0}
VTC_INFER_GIT_SHA=$(git rev-parse HEAD)
image_tag="${VTC_IMAGE_REPOSITORY}:${VTC_INFER_VERSION}-$(git rev-parse --short=12 HEAD)"

docker_cmd=(docker)
if ! docker info >/dev/null 2>&1; then
  docker_cmd=(sudo docker)
fi

"${docker_cmd[@]}" buildx build \
  --platform linux/amd64 \
  --load \
  --build-arg "VTC_INFER_VERSION=${VTC_INFER_VERSION}" \
  --build-arg "VTC_INFER_GIT_SHA=${VTC_INFER_GIT_SHA}" \
  --tag "$image_tag" \
  --file docker/Dockerfile .

"${docker_cmd[@]}" push "$image_tag"
repo_digest=$("${docker_cmd[@]}" image inspect "$image_tag" \
  --format '{{index .RepoDigests 0}}')

printf 'VTC_IMAGE=%s\n' "$image_tag"
printf 'VTC_IMAGE_REPO_DIGEST=%s\n' "$repo_digest"
