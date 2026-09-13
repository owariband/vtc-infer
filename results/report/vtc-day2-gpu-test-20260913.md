# VTC Day 2 GPU 测试简报

> 本报告记录同步扩展路径的历史结果。后续异步迁移及最终配对验收见
> `results/report/vtc-async-gpu-test-20260913.md`。

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
2.94～10.91 秒。后续自定义 FCFS 对照仅得到 1508.2 tok/s，证明主要损失来自
vLLM 自定义 `Scheduler` 的同步执行路径，而非 VTC 公平队列本身。

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

## 自定义 FCFS 隔离对照

`CustomFCFSScheduler` 不覆盖 vLLM 的任何调度方法，仍使用原生 FCFS 队列，但通过与 VTC
相同的 `scheduler_cls` 入口加载。首轮对照完成 1989/1989 个请求，输出吞吐为
1508.2 tok/s，waiting queue 正值为 177/180，最大值 496，dispatch lag P95 为 5.78 秒。
这些数据与 VTC 高度接近，而 tenant-b P95 TTFT 为 51.63 秒，说明：

- VTC 的低频租户延迟改善确实来自公平调度；
- 相对原生 FCFS 的约 36% 吞吐下降，主要是自定义同步 scheduler 路径的代价；
- 要恢复吞吐，优先级高于队列微优化的方向是适配 `AsyncScheduler` 或对固定 vLLM 版本
  做最小原生调度补丁。

注意：早期原生 FCFS 启动日志未显式锁定 model revision，而 VTC/自定义 FCFS 使用了
`989aa798...`。上述隔离对照足以定位同步路径开销，但正式最终对比仍应锁定所有参数后重跑。

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
