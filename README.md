# VTC-Infer

VTC-Infer 是一个基于 vLLM V1 的多租户公平调度实验项目。阶段一将在单张 GPU 上对比 FCFS、VTC 和实验性的 VTC-Miss，并记录公平性、延迟与吞吐结果。

## 目录

- `vtc_infer/`：调度算法与 vLLM 适配代码
- `benchmark/`：负载生成器与实验工作负载
- `analysis/`：指标计算、绘图与报告生成
- `tests/`：单元测试和冒烟测试
- `configs/`：服务与实验配置
- `scripts/`：启动、实验和报告入口
- `results/sample/`：可提交的小型示例数据
- `results/runs/`：完整实验结果，默认不提交 Git

当前实现的是 **async admission-fair VTC**：VTC 只重排 waiting/admission，running 请求的
逐 decode-step 次序仍由 vLLM 管理，不能表述为完整 decode VTC。服务必须同时传入
`--async-scheduling` 和
`--scheduler-cls tinyinfer.scheduler.vllm_adapter.VTCScheduler`。默认实验权重为
`TINYINFER_VTC_WP=1`、`TINYINFER_VTC_WQ=2`。

异步计费把已确认 service 与 in-flight pending service 分开：调度产生 output placeholder 时
预留，实际 output 返回时按接受 token 数结算；取消会释放剩余 reservation，stale 或重复
回调不会重复计费。公平排序使用 confirmed + pending，confirmed counter 本身只增不减。

同扩展入口的 FCFS 基线使用
`--scheduler-cls tinyinfer.scheduler.vllm_adapter.CustomAsyncFCFSScheduler`；该类只继承
vLLM `AsyncScheduler`，不覆盖调度策略。vLLM v0.29.0 对所有自定义 scheduler 无条件打印
同步降级提示，GPU 验证使用
`patches/vllm-v0.29.0-custom-async-scheduler-warning.patch` 让提示按实际基类显示；补丁只改
日志分支，不改调度行为。

2026-09-13 的三轮固定配置配对实验中，异步 VTC 吞吐为对应异步 FCFS 的
99.06%、101.56%、101.63%，tenant-b P95 TTFT 为对应基线的 11.27%、20.00%、21.85%。
完整记录见 `results/report/vtc-async-gpu-test-20260913.md`。

## 阶段一：运行 FCFS 基线

在本地或 GPU 主机创建轻量 Python 环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

确认 vLLM 服务已经按 `docs/environment-lock.md` 启动后运行：

```bash
python -m scripts.run_experiment \
  --workload benchmark/workloads/noisy_neighbor.yaml \
  --policy fcfs \
  --service-parameter max_model_len=4096 \
  --service-parameter max_num_seqs=16 \
  --service-parameter prefix_caching=true
```

命令会在 `results/runs/<experiment-id>/` 中保存 `manifest.json`、
`requests.jsonl` 和 `run_summary.json`。随后可从原始请求记录重新生成指标：

```bash
python -m analysis.report results/runs/<experiment-id>/requests.jsonl
```

默认 workload 是初始压力参数，不是固定结论。如果服务没有形成持续排队，优先逐步提高
`tenant-a.request_rate` 或降低 vLLM 的 `max_num_seqs`，并把最终配置随实验结果保留。
