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

当前已实现阶段一的 FCFS 基线数据闭环和原始 VTC 调度器；GPU 对照实验与
prefix-reuse 实验尚待完成。VTC 使用
`--scheduler-cls tinyinfer.scheduler.vllm_adapter.VTCScheduler` 加载，默认实验权重为
`TINYINFER_VTC_WP=1`、`TINYINFER_VTC_WQ=2`。

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
