# VTC-Infer 上线与交付 SOP

> 本 SOP 先覆盖阶段一的单机 MVP，并预先约定阶段二使用的镜像交付方式。阶段一不部署 Kubernetes、Production Stack、Prometheus 或 KEDA。

## 1. 阶段一目标

在一张 RTX 4090 上完成可复现的最小实验闭环：

```text
多租户开环负载
→ vLLM 产生排队
→ 对比 FCFS / VTC / VTC-Miss
→ 保存请求级 JSONL
→ 生成公平性、TTFT、吞吐和缓存命中图表
```

阶段一的退出条件：

- FCFS 与 VTC 使用同一模型、参数、执行路径和 workload；
- 至少一个 noisy-neighbor 场景能稳定产生 waiting queue；
- VTC 无死锁、请求丢失、counter 回退，并有单元测试；
- 每种策略至少重复运行 3 次，保存随机种子和原始数据；
- 一条命令可以启动服务，一条命令可以重跑实验并生成图表。

## 2. 机器配置

阶段一配置：

- Ubuntu 22.04；
- 1 × RTX 4090 24GB；
- 16 核 CPU；
- 64GB 系统内存；
- 100Gi 磁盘。
- Ubuntu-nvidia 22.04

100Gi 足以完成阶段一，但不要在机器上长期保留多个 CUDA/vLLM 镜像和构建缓存。每天用 `docker system df` 检查空间。不要在实验过程中执行会删除正在使用镜像或数据卷的清理命令。

### 阶段二磁盘建议

阶段二建议把系统盘或独立 Docker 数据盘扩到 **250Gi**；最低按 **200Gi** 准备。如果要在同一台机器从源码编译 patched vLLM、反复构建镜像，建议直接使用 **300Gi**。

典型预算：

| 内容 | 预算 |
|---|---:|
| Ubuntu、驱动和系统工具 | 20～30Gi |
| vLLM/CUDA 基础镜像与自定义运行镜像 | 25～45Gi |
| Docker 构建层；源码构建时会更高 | 40～80Gi |
| Qwen 小模型、Hugging Face 与 vLLM 编译缓存 | 10～25Gi |
| 单节点 Kubernetes、Production Stack 和监控镜像 | 15～30Gi |
| Prometheus、日志、实验结果及安全余量 | 30～50Gi |

如果只在 CI 构建镜像，目标机器只负责拉取和运行，200Gi 通常足够；如果在 GPU 机器本地开发和构建，250～300Gi 更稳。100Gi 不适合作为阶段二长期环境。

租机后首先确认 GPU 是完整直通设备，而不是限制功能的 vGPU：

安装驱动
```bash
wget
https://us.download.nvidia.com/XFree86/Linux-x86_64/595.99.02/NVIDIA-Linux-x86_64-595.99.02.run
# 上面的403
# 先开启multiverse源（Ubuntu默认关闭）
sudo apt-add-repository multiverse
sudo apt update

# 查看推荐驱动
ubuntu-drivers devices

# 直接安装595
sudo apt install nvidia-driver-595
# 或者自动安装推荐版本 sudo ubuntu-drivers autoinstall

sudo reboot
# 重启后验证
nvidia-smi
```
docker安装

```bash
 sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg

  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc

  sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
  Types: deb
  URIs: https://download.docker.com/linux/ubuntu
  Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
  Components: stable
  Architectures: $(dpkg --print-architecture)
  Signed-By: /etc/apt/keyrings/docker.asc
  EOF

  sudo apt-get update
  sudo apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

  sudo systemctl enable --now docker

sudo vim /etc/docker/daemon.json

#举例
{
    "registry-mirrors": [
        "https://docker.1ms.run",
        "https://docker.xuanyuan.me"
    ]
}
#重启docker服务
sudo systemctl restart docker
docker version
sudo docker run --rm --gpus all \
  nvidia/cuda:13.0.3-base-ubuntu22.04 nvidia-smi
```

最后一条失败时，先安装或修复 NVIDIA Container Toolkit，不进入项目开发。

## 3. 在哪里开发

所有 VTC-Infer 代码都应放在本仓库：

```text
/Users/yyu03/project/dev/vtc-infer
```

不要把核心实现只改在租用机器的 `site-packages`、临时容器或某个未提交的 vLLM 目录中，否则无法复现和构建镜像。

本仓库已配置 Git 远端。本地开发前先确认工作区和远端地址：

```bash
cd /Users/yyu03/project/dev/vtc-infer
git status
git remote -v
git remote set-url origin https://github.com/owariband/vtc-infer.git
git pull --ff-only
```

如果远端默认分支或地址不同，相应替换；不要重复添加已经存在的 `origin`。

推荐工作流是“本地编写和提交，GPU 云主机拉取并运行”。租用机器不要复制一份脱离 Git 的代码：

```bash
sudo mkdir -p /workspace
sudo chown "$(id -u):$(id -g)" /workspace
cd /workspace
git clone https://github.com/owariband/vtc-infer.git vtc-infer
cd vtc-infer
git rev-parse HEAD
```

后续每次实验前先提交本地变更并推送，然后在云主机拉取对应 commit。正式结果的 `manifest.json` 必须记录该完整 commit SHA。紧急在云主机调试出的修改也要形成 commit 并推回远端，不能只留在云主机。

建议按实施方案逐步形成：

```text
vtc-infer/
├── scheduler/          # VTC、VTC-Miss 和租户队列
├── benchmark/          # 开环负载生成器与固定 workload
├── analysis/           # 汇总、指标和绘图
├── tests/              # 调度与计费单元测试
├── scripts/            # 启动、停止和实验入口
├── patches/            # 必要时保存针对固定 vLLM commit 的最小 patch
├── docker/             # 阶段二使用的镜像定义
├── results/            # 原始数据和图表
└── docs/
```

`results/` 中只提交小型样例和最终报告。大量 JSONL、模型权重、虚拟环境、缓存和密钥必须加入 `.gitignore`。

## 4. vLLM 修改策略

固定使用实施方案约定的 vLLM `v0.29.0`，并记录最终使用的镜像 digest 或源码 commit。不要只记录浮动的 `latest` 标签。

优先顺序如下：

1. 优先把 VTC 写成仓库内可测试的 Python 包，通过 `scheduler_cls` 加载；
2. 如果 vLLM V1 的非稳定接口无法满足需求，只对固定 commit 维护最小 patch；
3. patch 文件保存在 `patches/`，并在 README 中记录基准 commit、应用命令和受影响文件；
4. 禁止只在租用机器中手改 vLLM 源码而不导出 patch。

即使最终需要 patch，租用机器上的 vLLM checkout 也只是上游依赖和调试工作区；VTC-Infer 仓库仍是项目交付、测试、配置与 patch 的唯一事实来源。

## 5. 阶段一动作清单

### 5.1 Day 0：Ubuntu 22.04 环境安装与验收

#### 步骤 1：记录机器基线

登录租用机器后先执行只读检查：

```bash
cat /etc/os-release
uname -m
lscpu
free -h
df -h /
nvidia-smi
```

期望结果：Ubuntu 22.04、`x86_64`、约 16 核 CPU、64GB 内存、RTX 4090 24GB。云厂商的 Ubuntu-NVIDIA 镜像通常已经安装驱动；`nvidia-smi` 正常时不要重复安装或随意升级驱动。

vLLM `v0.29.0` 官方 CUDA 镜像基于 CUDA 13.0.3。最终兼容性以“该镜像能否在容器内运行 `nvidia-smi` 和 vLLM smoke test”为准。如果出现 `CUDA driver version is insufficient`，让云厂商升级宿主机 NVIDIA 驱动，不要在不清楚 GPU 直通方式时自行覆盖驱动。

#### 步骤 2：安装基础工具

```bash
sudo apt-get update
sudo apt-get install -y \
  ca-certificates \
  curl \
  git \
  gnupg \
  jq \
  make \
  python3 \
  python3-venv
```

宿主机 Python 只用于轻量脚本和纯逻辑单元测试。不要在宿主机执行 `pip install vllm`，也不需要单独安装 CUDA Toolkit；vLLM、PyTorch 和 CUDA 用户态依赖由官方容器提供。

#### 步骤 3：安装 Docker Engine 与 buildx

如果云镜像已经提供可用的 Docker Engine 和 buildx，可以跳到步骤 4。否则使用 Docker 官方 apt 仓库：

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: jammy
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin

sudo systemctl enable --now docker
sudo docker version
sudo docker buildx version
sudo docker run --rm hello-world
```

本 SOP 默认使用 `sudo docker`，无需把登录用户加入 `docker` 组。`docker` 组等价于较高的宿主机权限，只有明确接受该风险时再配置免 sudo。

#### 步骤 4：安装 NVIDIA Container Toolkit

仅有 NVIDIA 驱动还不能让 Docker 使用 GPU，需要安装 Container Toolkit：

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor --yes \
  -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -sSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

先验证通用 CUDA 容器，再验证 vLLM 镜像所需的 CUDA 13：

```bash
sudo docker run --rm --gpus all \
  nvidia/cuda:13.0.3-base-ubuntu22.04 nvidia-smi
```

验收：容器中能看到同一张 RTX 4090，且没有 driver/runtime 错误。

#### 步骤 5：同步 VTC-Infer 远端仓库

本地开发机上的 `/Users/yyu03/project/dev/vtc-infer` 是当前项目仓库。先确认本地仓库指向正确的远端：

```bash
cd /Users/yyu03/project/dev/vtc-infer
git status
git remote set-url origin https://github.com/owariband/vtc-infer.git
git remote -v
git push -u origin main
```

然后在 Ubuntu GPU 机器上拉取：

```bash
sudo mkdir -p /workspace /data/tinyinfer/huggingface /data/tinyinfer/vllm-cache
sudo chown -R "$(id -u):$(id -g)" /workspace /data/tinyinfer
cd /workspace
git clone https://github.com/owariband/vtc-infer.git vtc-infer
cd vtc-infer
git rev-parse HEAD
```

如果模型或仓库需要凭据，只通过云厂商密钥服务、交互式登录或受限权限的环境文件提供；不要把 token 写入 Git、Dockerfile、镜像层或 shell 脚本。

#### 步骤 6：拉取并锁定 vLLM v0.29.0

`v0.29.0` 是 vLLM 正式 release，不使用浮动的 `latest`：

```bash
sudo docker pull vllm/vllm-openai:v0.29.0
sudo docker image inspect vllm/vllm-openai:v0.29.0 \
  --format '{{index .RepoDigests 0}}'
```

把输出的 `vllm/vllm-openai@sha256:...` 保存到项目的环境锁定记录。后续复现实验和自定义镜像都以该 digest 为基准。

#### 步骤 7：启动原生 FCFS vLLM

先使用公开小模型完成环境验证。正式实验前还要把模型 revision 固定为具体 commit；Day 0 初次启动可先省略 `--revision`，确认下载完成后再查询并锁定实际 revision。

```bash
sudo docker run -d \
  --name tinyinfer-vllm-fcfs \
  --gpus all \
  --ipc=host \
  -p 8000:8000 \
  -v /data/tinyinfer/huggingface:/root/.cache/huggingface \
  -v /data/tinyinfer/vllm-cache:/root/.cache/vllm \
  vllm/vllm-openai:v0.29.0 \
  Qwen/Qwen2.5-1.5B-Instruct \
  --max-model-len 4096 \
  --max-num-seqs 16 \
  --enable-prefix-caching
```

观察启动过程：

```bash
sudo docker logs -f tinyinfer-vllm-fcfs
```

模型加载完成并开始监听 8000 端口后，另开终端验收：

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models | jq

curl --fail http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "messages": [{"role": "user", "content": "Reply with exactly: VTC-Infer ready"}],
    "temperature": 0,
    "max_tokens": 16
  }' | jq
```

同时记录显存和容器状态：

```bash
nvidia-smi
sudo docker ps
sudo docker stats --no-stream tinyinfer-vllm-fcfs
sudo docker system df
```

验收完成后停止并删除测试容器，保留模型与编译缓存：

```bash
sudo docker stop tinyinfer-vllm-fcfs
sudo docker rm tinyinfer-vllm-fcfs
```

#### 步骤 8：锁定环境并建立项目骨架

在仓库中新增环境锁定记录，至少保存：

- Ubuntu 版本与内核；
- `nvidia-smi` 中的 GPU、driver 版本；
- Docker、Container Toolkit 和 vLLM 版本；
- vLLM 镜像完整 digest；
- `Qwen/Qwen2.5-1.5B-Instruct` 的具体 revision；
- `git rev-parse HEAD`；
- Day 0 smoke test 命令与结果。

然后创建阶段一所需的 `.gitignore`、README、`scheduler/`、`benchmark/`、`analysis/`、`tests/`、`scripts/` 和 `results/` 骨架。不要在 Day 0 安装 Kubernetes。

Day 0 最终退出条件：

- 宿主机和容器内都能看到 RTX 4090；
- vLLM `v0.29.0` 官方镜像 digest 已记录；
- Qwen2.5-1.5B 的 health、models 和 chat completion 全部成功；
- 模型与 vLLM cache 持久化到 `/data/tinyinfer`；
- VTC-Infer 远端仓库可从 GPU 机器 clone、pull 和定位到明确 commit；
- 删除测试容器后，磁盘仍至少保留 25Gi 可用空间。

### 5.2 Day 1：FCFS 基线

Day 1 先验收原生 FCFS 的数据闭环，不修改 scheduler。当前已提供：

- `benchmark/workloads/noisy_neighbor.yaml`：固定随机种子的双租户开环负载；
- `python -m scripts.run_experiment`：流式调用 OpenAI-compatible API；
- `requests.jsonl`：请求级原始记录；
- `python -m analysis.report`：从原始记录重算租户级 TTFT、service 和吞吐。

负载中 `tenant-a` 是高频、长输出租户，`tenant-b` 是低频、短输出租户。两者的
Poisson 到达序列在客户端分别生成；某个请求是否完成不会推迟后续请求的计划到达时间。
`max_in_flight` 只是防止客户端连接无限增长，不是服务端并发配置。

Day 1 按下面的 5.2.1～5.2.8 依次执行。退出条件是：

- workload 完成且无请求静默丢失；
- 请求级时间戳、状态和 token usage 能被解析；
- vLLM 的 waiting queue 在实验期间持续大于零，而不是偶发出现一个采样点；
- 同一 commit、配置和 seed 重复运行 3 次，负载请求数完全相同；
- 三次实验中 `tenant-b` 的 P95/P99 TTFT 趋势一致；
- 原始 `requests.jsonl` 可以独立重新生成 `analysis.json`。

只有同时满足“服务端排队”和“客户端没有明显发压滞后”，实验才能用于后续 FCFS/VTC
对照。如果客户端自身已经排队，测到的延迟不能归因于 vLLM scheduler。

#### 5.2.1 同步代码并安装负载生成器

以下命令在 Ubuntu GPU 主机的 VTC-Infer checkout 中执行。正式实验必须使用已提交的
commit；不要一边修改 workload 一边复用同一个实验编号。

```bash
cd /workspace/vtc-infer
git pull --ff-only
git status --short
git rev-parse HEAD

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest -q
```

期望 `git status --short` 没有输出，测试全部通过。`.venv` 仅包含客户端负载和分析依赖，
不在宿主机安装 vLLM、PyTorch 或 CUDA。

#### 5.2.2 启动并检查 FCFS 服务

如果 Day 0 的容器已删除，使用第 5.1 节步骤 7 的固定命令重新启动。不要在不同重复实验
之间更改 `max_model_len`、`max_num_seqs`、prefix caching 或 GPU memory 设置。

```bash
curl --fail --silent http://127.0.0.1:8000/health
curl --fail --silent http://127.0.0.1:8000/v1/models | jq
sudo docker inspect tinyinfer-vllm-fcfs --format '{{.Config.Image}} {{.State.Status}}'
nvidia-smi
```

在正式发压前发送一个带租户扩展字段的流式请求：

```bash
curl --fail --no-buffer http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "messages": [{"role": "user", "content": "Reply with VTC-Infer ready"}],
    "temperature": 0,
    "max_tokens": 16,
    "stream": true,
    "stream_options": {"include_usage": true},
    "vllm_xargs": {"tenant_id": "smoke-test"}
  }'
```

验收要求：HTTP 请求成功，能看到流式 `data:` 事件、最终 `[DONE]` 和非空 usage。该检查
只能证明 API 接受并传输了 `vllm_xargs`；Day 2 仍需通过 scheduler 日志或测试确认
`tenant_id` 已到达自定义 scheduler，不能仅凭 HTTP 200 作此结论。

再确认 vLLM 暴露 waiting queue 指标：

```bash
curl --fail --silent http://127.0.0.1:8000/metrics \
  | grep '^vllm:num_requests_waiting'
```

空闲时指标值应为 `0`。如果指标不存在，先检查 vLLM 版本和 `/metrics` 输出，不要用
GPU utilization 猜测是否排队。

#### 5.2.3 检查并理解 workload

正式运行前保存当前配置：

```bash
sed -n '1,200p' benchmark/workloads/noisy_neighbor.yaml
```

默认配置运行 120 秒，seed 为 `20260912`。每个租户的实际请求数由固定 seed 的 Poisson
序列决定，因此相同配置生成的请求编号和计划到达时间应完全一致。`prompt_tokens` 是构造
prompt 的目标长度；报告以服务端 usage 返回的实际 token 数为准。

第一次运行不要先改参数。只有确认默认配置没有形成持续 waiting queue 后，才逐级调节：

1. 将 `tenant-a.request_rate` 每次提高 25%；
2. 仍无法排队时，把服务端 `max_num_seqs` 从 16 降为 8；
3. 每次参数变化都创建新 commit 或保存独立 workload 文件，并使用新的实验编号；
4. 不同时调整请求率、输出长度和 `max_num_seqs`，否则无法解释是哪项变化造成差异。

#### 5.2.4 运行一次 FCFS workload

明确指定实验编号，避免同一分钟运行时目录名冲突。以下示例中的编号应按实际重复次数修改：

```bash
TINYINFER_EXPERIMENT_ID=fcfs-noisy-neighbor-seed20260912-r1

python -m scripts.run_experiment \
  --workload benchmark/workloads/noisy_neighbor.yaml \
  --policy fcfs \
  --experiment-id "$TINYINFER_EXPERIMENT_ID" \
  --service-parameter max_model_len=4096 \
  --service-parameter max_num_seqs=16 \
  --service-parameter prefix_caching=true \
  --service-parameter vllm_version=0.29.0 \
  --service-parameter vllm_image_digest=sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1 \
  --service-parameter model_revision=989aa7980e4cf806f80c7fef2b1adb7bc71aa306
```

运行器会等待全部请求结束，并输出结果目录。每次实验创建独立目录：

```text
results/runs/<experiment_id>/
├── manifest.json       # workload、Git 状态及命令显式传入的服务参数
├── requests.jsonl      # 请求级原始数据
└── run_summary.json    # 完成、成功和失败请求数
```

目录已存在时运行器会直接失败，不会覆盖旧实验。策略、参数、代码或重复次数变化后必须使用
新的 `experiment_id`。

#### 5.2.5 同时采样服务端 waiting queue

`requests.jsonl` 记录客户端观察到的请求时序；是否真正饱和必须由服务端指标证明。在另一个
终端运行以下采样。采样覆盖 120 秒发压以及排队请求排空所需的额外时间：

```bash
TINYINFER_EXPERIMENT_ID=fcfs-noisy-neighbor-seed20260912-r1

for TINYINFER_SAMPLE_INDEX in $(seq 1 180); do
  date +%s%3N
  curl --fail --silent http://127.0.0.1:8000/metrics \
    | awk '$1 == "vllm:num_requests_waiting" {print $2}'
  sleep 1
done > "/tmp/${TINYINFER_EXPERIMENT_ID}-waiting.raw"
```

实验结束后把采样文件转换成两列 TSV 并放入对应结果目录：

```bash
awk 'NR % 2 == 1 {timestamp=$0; next} {print timestamp "\t" $0}' \
  "/tmp/${TINYINFER_EXPERIMENT_ID}-waiting.raw" \
  > "results/runs/${TINYINFER_EXPERIMENT_ID}/waiting_queue.tsv"
```

如果 `curl` 失败，原始文件会出现奇数行，不能继续使用上述转换结果。先检查服务日志和
采样完整性，重新运行实验，不要手工补零。

#### 5.2.6 生成并查看分析结果

```bash
python -m analysis.report \
  "results/runs/${TINYINFER_EXPERIMENT_ID}/requests.jsonl"

jq . "results/runs/${TINYINFER_EXPERIMENT_ID}/run_summary.json"
jq . "results/runs/${TINYINFER_EXPERIMENT_ID}/analysis.json"
```

`analysis.json` 当前包含：

- 每租户总请求数、成功数和失败数；
- 每租户 P50/P95/P99 TTFT；
- 每租户实际输入加输出 token service；
- aggregate output-token throughput；
- service gap 和 Jain service index。

Jain index 不能单独作为 Day 1 的通过条件。当前两个租户的 offered load 和输出长度有意
不同，累计 service 本来就不会相同；而且让所有租户一起变慢也可能得到更好看的公平性。
它必须与 waiting queue、每租户尾延迟、吞吐和失败数一起解释。

#### 5.2.7 单次运行的数据完整性验收

先检查状态、usage 和客户端发压滞后：

```bash
jq -s '{
  total: length,
  by_status: group_by(.status) | map({status: .[0].status, count: length}),
  missing_first_token: map(select(.status == "ok" and .first_token_time == null)) | length,
  missing_output_usage: map(select(.status == "ok" and .output_tokens == null)) | length,
  max_dispatch_lag_seconds: map(.arrival_time - .scheduled_time) | max
}' "results/runs/${TINYINFER_EXPERIMENT_ID}/requests.jsonl"

awk 'BEGIN {positive=0; total=0; max=0}
     {total++; if ($2 > 0) positive++; if ($2 > max) max=$2}
     END {print "samples=" total, "positive=" positive,
                "positive_ratio=" positive/total, "max_waiting=" max}' \
  "results/runs/${TINYINFER_EXPERIMENT_ID}/waiting_queue.tsv"
```

单次运行必须满足：

- `run_summary.json` 的 request count 与 JSONL 行数一致；
- `failed_requests == 0`；任何失败都先查服务端日志，不能从报告中删除；
- 所有成功请求都有 `arrival_time`、`first_token_time`、`end_time` 和 output usage；
- 所有请求满足 `scheduled_time <= arrival_time <= first_token_time <= end_time`；
- dispatch lag 相比 TTFT 足够小且没有随实验持续增长；如其 P95 已达到数百毫秒，先排查
  客户端 CPU、连接数或网络，不能把这部分时间算作 scheduler 排队；
- waiting queue 多个连续采样点大于零。建议初始门槛为正值采样占发压窗口的 25% 以上；
  单个尖峰不算稳定饱和。

最后查看容器日志，确认没有 OOM、worker crash、请求取消或持续抢占：

```bash
sudo docker logs tinyinfer-vllm-fcfs \
  > "results/runs/${TINYINFER_EXPERIMENT_ID}/server.log" 2>&1
grep -Ei 'error|exception|traceback|out of memory|killed' \
  "results/runs/${TINYINFER_EXPERIMENT_ID}/server.log" || true
```

#### 5.2.8 重复性和 noisy-neighbor 验收

保持 commit、模型、服务启动参数、workload 和 seed 不变，依次运行 `r1`、`r2`、`r3`。
每次运行前等待 `vllm:num_requests_waiting` 回到 0，并留出短暂冷却时间；不要并行运行三组。

三次结果按以下规则验收：

- 三份 JSONL 的请求总数、各租户请求数、request ID 和 `scheduled_time` 完全一致；
- 三次均通过第 5.2.7 节的数据完整性与服务端排队门槛；
- 分别比较 `tenant-b` 的 P95/P99 TTFT 和 aggregate throughput，报告三次原始值，不只挑
  最好的一次；
- 若某次出现 OOM、HTTP 错误、客户端发压滞后或服务重启，该次标记为无效并说明原因，
  不能静默丢弃后只保留成功结果。

双租户实验中 `tenant-b` 尾延迟升高只能说明现象与竞争一致。若要严格声称 noisy-neighbor
造成退化，还需增加只保留 `tenant-b`、但其请求参数与 seed 生成规则不变的 control
workload，并比较单租户与双租户的 P95/P99 TTFT。没有 control 时，结论应写成“在饱和的
双租户 FCFS workload 中观察到低频租户尾延迟”，不能写成已证明因果关系。

Day 1 通过后再进入 VTC 开发。后续 FCFS 与 VTC 必须复用同一 workload、模型、服务参数
和分析脚本；唯一允许变化的是 scheduler policy 及其实现所必需且已记录的启动参数。

### 5.3 Day 2：VTC 调度

- 实现每租户 virtual counter、租户 FIFO、counter lift 和确定性 tie-break；
- admission 按输入 token 计费，decode 按实际输出 token 增量计费；
- 为计费、租户选择、重新活跃、取消和异常路径增加单元测试；
- 使用完全相同的 workload 对比 FCFS 与 VTC；
- 检查死锁、丢请求、counter 回退、吞吐异常和 scheduler CPU 开销。

验收：饱和负载下高频租户不能长期挤压持续活跃的低频租户。

### 5.4 Day 3：缓存实验与交付

- 增加共享长前缀和随机前缀两组 workload；
- 实现并明确标记实验性的 VTC-Miss 成本模型；
- FCFS、VTC、VTC-Miss 各重复至少 3 次；
- 自动生成 Jain index、service gap、P50/P95/P99 TTFT、TPOT、吞吐和 cache hit 图表；
- 编写 `scripts/run_server.sh`、`scripts/run_experiment.sh` 和 `scripts/render_report.sh`；
- 完成 README、已知限制、复现命令和 3～5 分钟演示。

验收：从干净 checkout 按 README 能重新运行至少一组小规模实验。

## 6. 阶段一是否需要发布镜像

不强制。阶段一的首要目标是验证调度算法和实验可信度，可以先通过官方 vLLM 容器挂载本仓库代码进行开发：

```text
宿主机 VTC-Infer checkout
→ 只读或开发态挂载到容器
→ 安装本地 scheduler 包
→ 启动固定版本 vLLM
```

阶段一结束时至少需要一个可复现的启动脚本。建议同时构建一个候选镜像做 smoke test，但正式的不可变镜像是阶段二的进入门槛。

## 7. 镜像打包方案

### 7.1 推荐路径：scheduler 包可独立加载

在 `docker/Dockerfile` 中：

1. 使用固定 digest 的官方 `vllm/vllm-openai:v0.29.0` 作为基础镜像；
2. 构建 VTC-Infer wheel；
3. 使用 `pip install --no-deps` 安装 wheel；
4. 设置默认 entrypoint 或保留 vLLM 原有 entrypoint；
5. 通过启动参数选择 VTC-Infer scheduler。

这种方式构建快、变更面小，也容易证明 VTC-Infer 与上游 vLLM 的边界。

### 7.2 备选路径：必须修改 vLLM 内部

如果 `scheduler_cls` 无法满足实现要求：

1. 在 Docker build 中 checkout 已固定的 vLLM commit；
2. 使用仓库内 `patches/*.patch` 应用补丁；
3. patch 应用失败时立即终止构建；
4. 构建并安装 patched vLLM；
5. 在镜像 label 和实验 manifest 中写入上游 commit 与 VTC-Infer commit。

不要在 Dockerfile 中 clone 浮动的 `main`，也不要下载未经校验的临时源码包。

## 8. 构建、验证和发布镜像

建议在租用的 x86 GPU 云主机上完成最终镜像构建、GPU smoke test 和推送。Mac 本地可以做普通 Python 测试，但不能替代 Linux + NVIDIA 环境验证。

先定义本次发布标识。镜像标签必须包含版本和 Git SHA，不使用 `latest` 作为部署依据：

```bash
cd /Users/yyu03/project/dev/vtc-infer
TINYINFER_REGISTRY_IMAGE=<REGISTRY>/<NAMESPACE>/tinyinfer-vllm
TINYINFER_VERSION=0.1.0
TINYINFER_GIT_SHA=$(git rev-parse --short=12 HEAD)
TINYINFER_IMAGE=${TINYINFER_REGISTRY_IMAGE}:${TINYINFER_VERSION}-${TINYINFER_GIT_SHA}
```

构建单机 4090 使用的 amd64 镜像：

```bash
docker buildx build \
  --platform linux/amd64 \
  --load \
  --label org.opencontainers.image.revision=${TINYINFER_GIT_SHA} \
  --tag ${TINYINFER_IMAGE} \
  --file docker/Dockerfile .
```

发布前必须完成：

```bash
docker run --rm --gpus all ${TINYINFER_IMAGE} nvidia-smi
./scripts/smoke_test_image.sh ${TINYINFER_IMAGE}
```

smoke test 至少验证：

- 镜像能看到 GPU；
- vLLM 版本和 VTC-Infer Git SHA 正确；
- FCFS 与 VTC 配置都能启动；
- `/health`、`/v1/models` 和一次流式请求成功；
- 配置错误时启动失败，而不是静默退回 FCFS。

登录所选镜像仓库后推送：

```bash
docker push ${TINYINFER_IMAGE}
```

推送后记录不可变 digest：

```bash
docker buildx imagetools inspect ${TINYINFER_IMAGE}
```

把完整的 `image@sha256:...` 写入发布记录和阶段二 Helm values。部署时优先使用 digest，而不是可被覆盖的 tag。

## 9. 发布门禁与回滚

创建 Git tag 前必须满足：

- 工作区干净，代码和实验配置已提交；
- 单元测试和镜像 smoke test 通过；
- 至少一组 FCFS/VTC 结果可以从原始 JSONL 重新生成；
- README 已记录模型、依赖、已知限制和复现命令；
- 镜像扫描没有未说明的严重漏洞；
- 镜像 digest 已记录。

发布代码版本：

```bash
git tag -a v0.1.0 -m "VTC-Infer phase-1 MVP"
git push origin v0.1.0
```

容器镜像不可原地覆盖。回滚就是把启动脚本或阶段二 Helm values 恢复到上一个已验证的 `image@sha256:...`。

## 10. 阶段一交付清单

- [ ] VTC-Infer Git 远端和首个基线提交；
- [ ] 固定版本的 vLLM、模型 revision 和依赖锁；
- [ ] FCFS、VTC、VTC-Miss 策略实现与配置开关；
- [ ] 单元测试和镜像 smoke test；
- [ ] noisy-neighbor 与 prefix-reuse workload；
- [ ] 每种策略至少 3 次原始结果；
- [ ] 自动分析和绘图脚本；
- [ ] 单机启动、停止和复现实验命令；
- [ ] 候选镜像 tag、digest 和发布记录；
- [ ] README、限制说明和演示材料。

阶段一全部通过后，阶段二再增加 Production Stack Helm values、Router、Prometheus/Grafana、readiness 和回滚演练。
