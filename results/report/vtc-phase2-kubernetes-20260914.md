# VTC-Infer 阶段二 Kubernetes 验收报告（2026-09-14）

## 结论

阶段二通过。Production Stack 单 GPU 服务可在 FCFS/VTC 间通过 Helm values 切换；正式六轮
回归全部完成 1989/1989 请求且零失败。VTC 吞吐为配对 FCFS 的 98.73%～101.39%，低频租户
tenant-b 的 P95 TTFT 为 FCFS 的 9.94%～23.28%。Engine/Router Prometheus targets 均为 up，
Grafana API 已发现 `VTC-Infer Overview`。Pod 重建和 Helm rollback 均能恢复，但单副本存在
约 1～2 分钟不可用窗口。

## 环境锁

- GPU：1 × RTX 4090 24GB；k3s `v1.36.4+k3s1`；Helm `v3.22.0`。
- Git：实验与部署配置 `3dba9196316711c47eec81983a3f668243adac3f`，工作区干净。
- Engine：vLLM `v0.29.0`，镜像构建 commit `81bfe6e090e3`，digest
  `sha256:c910c511eae516b66b7c4a8285a0e835b7d2726e83c4f33ea73602b1b1ec7881`。
- Router：`v0.1.12`，digest
  `sha256:d8cfaf022f0179ba3f9d2bbcb95c602bd639b700f7a6ac409626758d1a366483`。
- Chart：Production Stack `0.1.12`，模型 `Qwen/Qwen2.5-1.5B-Instruct` revision
  `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`。
- 公共参数：120 秒、seed `20260912`、`max_num_seqs=16`、`max_model_len=4096`、prefix cache
  开启、VTC `wp=1/wq=2`。

负载生成器运行在 `gpu1` 宿主机，直连 Router ClusterIP。一次经 `kubectl port-forward` 的
FCFS 预跑因 broken pipe 产生 342 个客户端失败，已排除在正式结果之外。

## 配对实验

| 轮次 | FCFS 吞吐 tok/s | VTC 吞吐 tok/s | VTC/FCFS | FCFS tenant-b P95 TTFT | VTC tenant-b P95 TTFT | TTFT 比 | E2E 比 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2287.86 | 2319.75 | 101.39% | 0.666s | 0.155s | 23.28% | 38.96% |
| 2 | 2302.56 | 2283.99 | 99.19% | 0.791s | 0.181s | 22.92% | 39.09% |
| 3 | 2362.17 | 2332.20 | 98.73% | 1.311s | 0.130s | 9.94% | 20.46% |

六轮耗时 121～122 秒，dispatch-lag P95 为 1.56～1.69 ms。每轮失败请求、缺失首 token、
缺失 usage 和非法时间戳均为 0，满足预设门槛。

## 部署、恢复与可观测性

- 单 GPU 使用 `Recreate`，避免 RollingUpdate 时新旧 Pod 争抢唯一 GPU。
- 固定 revision 模型缓存在 PVC 中；缓存完整后 Engine 离线启动。FCFS/VTC 切换约 95～96 秒。
- 两次 Engine Pod 重建分别在 81 秒、111 秒恢复。真实 chat 在重建期间返回 503，Ready 后
  恢复 200；`/v1/models` 不能单独作为推理可用性探针。
- 健康 VTC revision 11 回滚至 FCFS revision 10 耗时 85 秒，API smoke 与监控恢复；最终再
  升级至 VTC revision 13。
- 最终 revision 13 为 `deployed`；Engine、Router、Prometheus、Grafana 和 Operator Pod
  Ready、重启数为 0。Engine/Router targets 为 up，Grafana 能发现版本管理的 dashboard。
- 错误 scheduler class 演练按预期 CrashLoop/fail-fast，没有静默退回 FCFS。

## 限制与证据

本验收是单节点、单副本、单 GPU 固定容量交付，不代表跨 Pod 公平、自动扩缩、认证/TLS 或
零停机升级。首次填充模型缓存仍依赖 Hugging Face 网络。本地 registry 仅适用于此单节点
验收环境。

原始证据位于本地未提交目录 `results/remote/gpu1-20260914-phase2/`；正式配对汇总为
`experiments-clusterip-final/paired-summary.json`，六轮请求级 JSONL 位于其 `runs/` 子目录，
Prometheus/Grafana 证据位于 `final-observability/`，回滚与最终状态位于
`attempt-12-clean-rollback-fcfs/` 和 `attempt-13-final-vtc/`。
