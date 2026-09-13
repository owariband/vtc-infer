# Async admission-fair VTC GPU 验收报告

实验日期：2026-09-13
实验主机：`gpu1`（1 × NVIDIA GeForce RTX 4090 24GB）
代码固定点：`ba31bd131495fcc1300771de719513049ddb8f3e` 加本报告对应未提交 diff

## 结论

现有 admission-fair VTC 已迁移到 vLLM v0.29.0 `AsyncScheduler`。三次固定配置配对实验
中，VTC 输出吞吐分别达到异步自定义 FCFS 的 99.06%、101.56%、101.63%，均高于 90%
门槛；tenant-b P95 TTFT 分别降至对应 FCFS 的 11.27%、20.00%、21.85%，均低于 50%
门槛。三轮 VTC dispatch-lag P95 为 1.68～1.79 ms，低于 100 ms。

本阶段实现的是 **async admission-fair VTC**：只对 waiting/admission 做租户公平排序。
running 请求仍由 vLLM 原生逻辑处理，不宣称实现完整逐 decode-step VTC。

## 固定环境

- vLLM `v0.29.0`，镜像 digest
  `sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1`
- 模型 `Qwen/Qwen2.5-1.5B-Instruct`，revision
  `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`
- workload `benchmark/workloads/noisy_neighbor.yaml`，seed `20260912`
- `max_model_len=4096`、`max_num_seqs=16`、prefix caching 开启
- 两种策略均显式使用 `--async-scheduling`
- FCFS：`CustomAsyncFCFSScheduler`；VTC：`VTCScheduler`，`wp=1`、`wq=2`
- vLLM 日志提示补丁：`patches/vllm-v0.29.0-custom-async-scheduler-warning.patch`
  （仅按实际基类控制降级提示，不修改调度逻辑）

## 三次配对结果

| 轮次 | FCFS 吞吐 | VTC 吞吐 | VTC/FCFS | FCFS tenant-b P95 | VTC tenant-b P95 | VTC/FCFS | VTC dispatch-lag P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| r1 | 2319.84 tok/s | 2297.97 tok/s | 99.06% | 1.197 s | 0.135 s | 11.27% | 1.70 ms |
| r2 | 2312.35 tok/s | 2348.45 tok/s | 101.56% | 0.848 s | 0.170 s | 20.00% | 1.68 ms |
| r3 | 2265.35 tok/s | 2302.22 tok/s | 101.63% | 0.770 s | 0.168 s | 21.85% | 1.79 ms |

每轮两种策略均完成 1989/1989 个请求，`failed_requests`、缺失 first-token、缺失 output
usage 和非法时间戳顺序均为 0。三轮 VTC waiting queue 最大值分别为 19、29、29，正值
采样数分别为 41、50、50。六份服务日志均无 traceback、OOM 或 worker crash。

## 异步计费与兼容性

`VTCState` 分开暴露 confirmed counter、pending service 和两者之和。每个产生 output
placeholder 的调度批次取得唯一 reservation；输出返回时以实际接受 token 数结算。取消
清理该请求的全部 pending reservation，已取消请求的迟到输出和重复结算句柄都是 no-op。
抢占不会退款 confirmed counter，可交付 stale output 仍通过原 reservation 结算一次。

GPU 日志确认两种自定义类均在 `async_scheduling=True` 下加载。正式运行日志不含
“subclassed Scheduler instead of AsyncScheduler”降级提示。speculative decoding、LoRA 和
远端 KV connector 仍保持 fail-fast；缺失 `tenant_id` 的请求使用 `__default__`，smoke 后
EngineCore 保持健康。

## Smoke 与数据位置

带租户、缺失租户以及双租户并发的四个流式请求均收到 `[DONE]` 和 usage。完整请求记录、
分析、waiting queue、日志、container inspect 与 smoke SSE 位于：

```text
results/remote/gpu1-20260913-async/
```

结果由未提交 worktree 的独立远端临时副本生成；六份 manifest 均记录同一 HEAD
`ba31bd131495fcc1300771de719513049ddb8f3e` 且 `git_dirty=true`。未执行 commit、push、PR、
部署或 tracker 修改。
