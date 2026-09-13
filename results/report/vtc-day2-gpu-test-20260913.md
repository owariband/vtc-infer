# VTC Day 2 GPU 测试简报

实验日期：2026-09-13  
实验主机：`ubuntu@106.75.68.80`（1 × NVIDIA GeForce RTX 4090 24GB）  
最终代码 commit：`1dd23a9ddead4dcbe869dec6580242deee9d7c71`

## 结论

VTC 调度器已通过 GPU 启动、单租户、默认租户和双租户并发冒烟测试。三次 120 秒
noisy-neighbor 实验均完成 1989 个请求，无失败、无缺失 usage、无时间戳顺序错误，
服务日志未发现 error、OOM 或 worker crash。

在持续饱和下，低频租户 tenant-b 的 P95 TTFT 为 0.195～0.293 秒，明显低于 FCFS 基线的
0.800～1.338 秒，说明 VTC 有效防止了高频租户长期挤压低频租户。但输出吞吐为
1445～1507 tok/s，低于 FCFS 的 2295～2335 tok/s；同时客户端 dispatch lag P95 达
2.94～10.91 秒。因此公平性改善已经明确，但吞吐降低尚不能全部归因于 scheduler，
需先消除负载生成器的发压滞后再做严格性能对比。

## 固定环境

- vLLM `v0.29.0`，模型 `Qwen/Qwen2.5-1.5B-Instruct`
- `max_model_len=4096`，`max_num_seqs=16`，prefix caching 开启
- VTC 权重 `wp=1`、`wq=2`，async scheduling 关闭
- tenant-a：16 req/s，tenant-b：1 req/s，workload seed `20260912`

## 三次正式结果

| 运行 | 成功/总数 | waiting 正值 | 最大 waiting | tenant-b P95 | tenant-b P99 | 输出吞吐 |
|---|---:|---:|---:|---:|---:|---:|
| r1 | 1989/1989 | 177/180 | 496 | 0.293 s | 0.440 s | 1445.0 tok/s |
| r2 | 1989/1989 | 177/180 | 496 | 0.233 s | 0.271 s | 1507.1 tok/s |
| r3 | 1989/1989 | 177/180 | 496 | 0.195 s | 0.289 s | 1505.6 tok/s |

## 测试中修复的问题

- 移除了对 `max_concurrent_batches` 的 async scheduling 误判。
- 缺失 `tenant_id` 时改用保留租户 `__default__`，避免 vLLM EngineCore 因异常整体退出。
- 修正了 vLLM 0.29.0 带 label 的 waiting queue 指标匹配式。

首次采样无效的诊断运行已保留为
`vtc-noisy-neighbor-seed20260912-r1-invalid-waiting-sampler`，不纳入上述结论。

## 数据位置

完整请求记录、分析、waiting queue、服务日志及容器配置位于：

```text
results/remote/gpu1-20260913/
```
