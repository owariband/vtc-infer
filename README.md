# TinyInfer

TinyInfer 是一个基于 vLLM V1 的多租户公平调度实验项目。阶段一将在单张 GPU 上对比 FCFS、VTC 和实验性的 VTC-Miss，并记录公平性、延迟与吞吐结果。

## 目录

- `tinyinfer/`：调度算法与 vLLM 适配代码
- `benchmark/`：负载生成器与实验工作负载
- `analysis/`：指标计算、绘图与报告生成
- `tests/`：单元测试和冒烟测试
- `configs/`：服务与实验配置
- `scripts/`：启动、实验和报告入口
- `results/sample/`：可提交的小型示例数据
- `results/runs/`：完整实验结果，默认不提交 Git

当前仓库仅保留阶段一目录骨架，代码和配置将在开发过程中按需创建。
