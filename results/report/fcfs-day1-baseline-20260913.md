# FCFS Day 1 基线实验简报

实验日期：2026-09-13  
实验主机：`ubuntu@106.75.68.80`（1 × NVIDIA GeForce RTX 4090 24GB）

## 结论

默认 `tenant-a.request_rate=12.5` 只能产生短暂队列，三次运行的 waiting queue 正值采样占比为 4.44%～5.56%，未达到 SOP 建议的 25% 持续排队门槛。

将 `tenant-a.request_rate` 单独提高到 `16.0` 后，三次运行的正值采样占比为 27.78%～30.00%，最大 waiting 为 24～29，且最长连续排队为 19～21 秒。该配置能够稳定造成服务端排队，可作为后续 FCFS/VTC 对照实验的固定 workload。

tenant-b-only 对照组没有出现排队。与对照组相比，双租户场景下 tenant-b 的 P95 TTFT 放大约 30～59 倍，P99 TTFT 放大约 40～66 倍，说明当前 workload 存在显著的 noisy-neighbor 现象。

## 固定环境

- 模型：`Qwen/Qwen2.5-1.5B-Instruct`
- vLLM：`v0.29.0`
- 镜像 digest：`sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1`
- 模型 revision：`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`
- `max_model_len=4096`
- `max_num_seqs=16`
- prefix caching：开启
- workload 时长：120 秒
- waiting queue 采样：每秒一次，共 180 次
- seed：`20260912`
- FCFS rate=16 workload commit：`f3f25d38f70a54dd4bed87ef13c03612b0481618`
- tenant-b control workload commit：`7c71abb55d6a43dfd3f4323cbafe078667c6990a`

双租户配置中 tenant-a 为 16 req/s、512 prompt tokens、最多输出 256 tokens；tenant-b 为 1 req/s、128 prompt tokens、最多输出 32 tokens。对照组仅保留 tenant-b，且其参数与 seed 不变。

## 双租户 FCFS 结果

| 运行 | 请求 | 失败 | waiting 正值 | 正值占比 | 最大 waiting | 最长连续排队 | tenant-b P95 TTFT | tenant-b P99 TTFT | 输出吞吐 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| r1 | 1989 | 0 | 54/180 | 30.00% | 24 | 20 秒 | 0.800 s | 1.191 s | 2334.8 tok/s |
| r2 | 1989 | 0 | 50/180 | 27.78% | 25 | 21 秒 | 0.992 s | 1.217 s | 2294.5 tok/s |
| r3 | 1989 | 0 | 52/180 | 28.89% | 29 | 19 秒 | 1.338 s | 1.562 s | 2311.7 tok/s |

三次运行均有 1875 个 tenant-a 请求和 114 个 tenant-b 请求，请求 ID 与计划到达时间完全一致。所有请求均有首 token、结束时间及 output usage，时间戳顺序合法。客户端 dispatch lag P95 为 1.75～1.82 ms，服务日志未发现 error、exception、traceback、OOM 或 killed。

## tenant-b-only 对照结果

| 运行 | 请求 | 失败 | waiting 正值 | tenant-b P95 TTFT | tenant-b P99 TTFT | 输出吞吐 |
|---|---:|---:|---:|---:|---:|---:|
| r1 | 117 | 0 | 0/180 | 0.0268 s | 0.0301 s | 31.61 tok/s |
| r2 | 117 | 0 | 0/180 | 0.0200 s | 0.0223 s | 31.61 tok/s |
| r3 | 117 | 0 | 0/180 | 0.0225 s | 0.0238 s | 31.61 tok/s |

三次对照运行均无请求失败、缺失字段、时间戳顺序错误或服务日志错误。

## 对照解释与限制

当前负载生成器对所有租户共享一个由 workload seed 初始化的随机数流，并按租户顺序生成到达时间。删除 tenant-a 后，tenant-b 虽保持相同参数、seed 和 Poisson 生成规则，但不会得到与双租户实验逐请求相同的到达序列：对照组为 117 个 tenant-b 请求，双租户组为 114 个。因此本实验是分布级对照，而非严格的逐请求配对实验。

该限制不改变当前定性结论：对照组始终无服务端排队且 P99 TTFT 约为 22～30 ms，而双租户组持续排队且 P99 TTFT 为 1.19～1.56 s，差异远大于三次运行间波动。若后续需要更严格的配对因果分析，应让负载生成器为每个 tenant 派生独立且稳定的随机数流，并重新运行实验组和对照组。

## 数据位置

原始数据已回传至：

```text
results/remote/106.75.68.80-20260913/
```

每个有效运行目录均包含 `manifest.json`、`requests.jsonl`、`run_summary.json`、`analysis.json`、`waiting_queue.tsv` 和 `server.log`。

## 阶段判定

FCFS Day 1 的稳定排队、重复性、数据完整性和客户端无明显发压滞后要求均已满足。建议后续 FCFS/VTC 实验固定使用 `tenant-a.request_rate=16.0` 及上述服务参数，唯一改变 scheduler policy 和其必需的已记录启动参数。
