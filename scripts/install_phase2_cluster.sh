#!/usr/bin/env bash
set -euo pipefail

K3S_VERSION=v1.36.4+k3s1
HELM_VERSION=v3.22.0
NVIDIA_DEVICE_PLUGIN_VERSION=0.20.0
KUBECONFIG_PATH=/workspace/.kube/vtc-infer-config

if ! command -v nvidia-container-runtime >/dev/null 2>&1; then
  echo "nvidia-container-runtime is required before installing k3s" >&2
  exit 1
fi

if ! command -v k3s >/dev/null 2>&1; then
  curl -fsSL https://get.k3s.io -o /tmp/install-k3s.sh
  sudo env \
    INSTALL_K3S_VERSION="$K3S_VERSION" \
    INSTALL_K3S_EXEC="server --disable traefik --disable servicelb" \
    sh /tmp/install-k3s.sh
fi

sudo install -d -m 0700 -o "$(id -u)" -g "$(id -g)" /workspace/.kube
sudo install -m 0600 -o "$(id -u)" -g "$(id -g)" \
  /etc/rancher/k3s/k3s.yaml "$KUBECONFIG_PATH"
export KUBECONFIG="$KUBECONFIG_PATH"

if ! command -v helm >/dev/null 2>&1; then
  helm_archive="helm-${HELM_VERSION}-linux-amd64.tar.gz"
  helm_tmp=$(mktemp -d /tmp/vtc-infer-helm.XXXXXX)
  curl -fsSLo "$helm_tmp/$helm_archive" "https://get.helm.sh/${helm_archive}"
  curl -fsSLo "$helm_tmp/${helm_archive}.sha256sum" \
    "https://get.helm.sh/${helm_archive}.sha256sum"
  (cd "$helm_tmp" && sha256sum --check "${helm_archive}.sha256sum")
  tar -xzf "$helm_tmp/$helm_archive" -C "$helm_tmp"
  sudo install -m 0755 "$helm_tmp/linux-amd64/helm" /usr/local/bin/helm
fi

if ! sudo docker inspect vtc-infer-registry >/dev/null 2>&1; then
  sudo docker run -d \
    --name vtc-infer-registry \
    --restart unless-stopped \
    -p 5000:5000 \
    registry:2.8.3
fi

sudo install -d -m 0755 /etc/rancher/k3s
if [[ ! -f /etc/rancher/k3s/registries.yaml ]]; then
  sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<'EOF'
mirrors:
  "localhost:5000":
    endpoint:
      - "http://127.0.0.1:5000"
EOF
  sudo systemctl restart k3s
fi

kubectl wait --for=condition=Ready node --all --timeout=180s
kubectl get runtimeclass nvidia

helm repo add nvdp https://nvidia.github.io/k8s-device-plugin --force-update
helm repo add vllm https://vllm-project.github.io/production-stack --force-update
helm repo update
helm upgrade --install nvidia-device-plugin nvdp/nvidia-device-plugin \
  --version "$NVIDIA_DEVICE_PLUGIN_VERSION" \
  --namespace nvidia-device-plugin \
  --create-namespace \
  --set runtimeClassName=nvidia \
  --wait --timeout 5m

kubectl delete pod vtc-infer-gpu-smoke --ignore-not-found
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: vtc-infer-gpu-smoke
spec:
  restartPolicy: Never
  runtimeClassName: nvidia
  containers:
    - name: cuda
      image: nvidia/cuda:13.0.3-base-ubuntu22.04
      command: ["nvidia-smi"]
      resources:
        limits:
          nvidia.com/gpu: "1"
EOF
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded \
  pod/vtc-infer-gpu-smoke --timeout=5m
kubectl logs vtc-infer-gpu-smoke
kubectl get node -o json \
  | jq -e '.items[].status.allocatable["nvidia.com/gpu"] == "1"'
