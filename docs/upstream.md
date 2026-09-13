# 阶段二上游与运行版本锁定

本文件记录 2026-09-14 `gpu1` 单 GPU 验收实际使用的上游、镜像和已知限制。可执行配置的
事实来源仍是 `deploy/production-stack/chart.lock.yaml` 与两个正式 values 文件。

## 版本与 digest

| 组件 | 锁定值 |
|---|---|
| Production Stack Chart | `vllm-stack 0.1.12` |
| Production Stack tag / commit | `vllm-stack-0.1.12` / `66b60661aa3052810859a417559e9e830772a091` |
| Chart archive SHA256 | `a33248ff71c12b600774ec084c1d68e2a632d00132fc0f8b6cad4b52ca9eb0d3` |
| vLLM | `v0.29.0`，V1 async scheduling |
| vLLM 基础镜像 digest | `sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1` |
| VTC-Infer Engine 镜像 | `localhost:5000/vtc-infer-vllm:0.2.0-81bfe6e090e3` |
| Engine manifest digest | `sha256:c910c511eae516b66b7c4a8285a0e835b7d2726e83c4f33ea73602b1b1ec7881` |
| Router 上游镜像 | `lmcache/lmstack-router:v0.1.12` |
| Router manifest digest | `sha256:d8cfaf022f0179ba3f9d2bbcb95c602bd639b700f7a6ac409626758d1a366483` |
| 模型 / revision | `Qwen/Qwen2.5-1.5B-Instruct` / `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` |
| k3s / Helm | `v1.36.4+k3s1` / `v3.22.0` |
| NVIDIA device plugin | `0.20.0` |
| kube-prometheus-stack dependency | `82.4.3` |

Engine 镜像构建自 `81bfe6e090e3`；最终负载生成器、Helm values 和验收记录来自干净提交
`3dba9196316711c47eec81983a3f668243adac3f`。两者不能混写为同一个 build SHA。

## Chart 适配与限制

- Chart 以 `repository:tag` 拼接镜像，因此 digest 放在 tag 中，最终格式为
  `repository:immutable-tag@sha256:digest`。
- 单 GPU 单副本 Engine 使用 `Recreate`。默认 RollingUpdate 会因旧 Pod 占用唯一 GPU 而
  使新 Pod Pending；Recreate 会带来可见停机窗口。
- 不在 `servingEngineSpec.labels` 放策略标签：Chart 会把它写入 immutable Deployment
  selector。策略由 scheduler class、`VTC_INFER_POLICY` 和 Helm revision 追溯。
- 不覆盖 `app.kubernetes.io/part-of=vllm-stack`，Prometheus 依赖该标签选择 ServiceMonitor。
- 模型缓存由固定 revision 的 init container 填充 PVC；缓存完整后 Engine 使用
  `HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1`。首次填充仍依赖 Hugging Face 网络。
- Router `/v1/models` 在 Engine 缺失时可能仍返回 200；可用性检查必须发送真实 chat 请求。
- `kubectl port-forward` 只用于 smoke、Prometheus 和 Grafana 管理访问，不用于高并发压测。
- 本阶段只覆盖单节点、单副本、单 GPU、round-robin Router；不包含 KEDA、多副本、跨 Pod
  公平、TLS、认证或零停机升级。
