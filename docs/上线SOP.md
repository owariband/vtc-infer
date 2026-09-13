# VTC-Infer 上线与交付 SOP

> 本 SOP 覆盖阶段一单机 MVP 与阶段二 Production Stack 工程化交付。阶段一不部署
> Kubernetes、Production Stack、Prometheus 或 KEDA；阶段二只做单副本、单 GPU 的固定
> 容量服务，不引入 KEDA、多副本或集群级公平。

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
TINYINFER_EXPERIMENT_ID=fcfs-noisy-neighbor-seed20260912-r3

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
TINYINFER_EXPERIMENT_ID=fcfs-noisy-neighbor-seed20260912-r3

for TINYINFER_SAMPLE_INDEX in $(seq 1 180); do
  date +%s%3N
  curl --fail --silent http://127.0.0.1:8000/metrics \
    | awk '$1 ~ /^vllm:num_requests_waiting\{/ {print $2}'
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

Day 2 的目标是在固定的 vLLM `v0.29.0` 上完成 async admission-fair VTC，并复用 Day 1
的模型、负载、分析链路和服务参数做公平对照。实现必须保持 work-conserving：只要有可
运行请求和资源，不能因为公平排序让 GPU 空转。本阶段只改变 waiting/admission 次序，不
宣称实现完整逐 decode-step VTC。

#### 5.3.1 开发计划与变更边界

按以下顺序执行：

1. 在 `tinyinfer/scheduler/vtc.py` 实现无 vLLM 依赖的状态核心；
2. 在 `tinyinfer/scheduler/vllm_adapter.py` 实现 vLLM `scheduler_cls` 最小适配；
3. 先跑 counter、lift、FIFO 和确定性测试，再做固定版本接口检查；
4. 在 GPU 主机启动 VTC，完成单请求和双租户 smoke test；
5. 使用 Day 1 同一 workload 连续跑 3 次 VTC；
6. 对照 FCFS/VTC 的完整性、公平性、吞吐和日志，判定退出条件。

核心规则固定如下：

- 每租户维护一个只增不减的 virtual counter；
- 新请求从 waiting queue 被接纳运行时按 `input_tokens × wp` 计费一次；仍在等待即取消的
  请求不计费，已接纳后取消的请求不退款；
- 模型调度 output placeholder 时按 `output_tokens × wq` 建立 pending reservation，实际
  接受输出后把对应 reservation 结算为 confirmed service，不按 `max_tokens` 预估；
- 公平排序使用 confirmed + pending service；取消释放未结算 reservation，stale output 和
  重复回调最多结算一次，confirmed counter 不回退；
- 每次从 waiting queue 选择 counter 最小租户的队首请求；
- 同一租户严格按进入 scheduler 的顺序 FIFO；跨租户 counter 相同则按全局到达序号、
  `request_id` 确定性排序；
- 租户从无 outstanding request 变为重新活跃时，将旧 counter 提升到当前活跃租户最小
  counter，再收取本次输入成本，防止积累无限历史额度；
- 默认 `wp=1`、`wq=2`，通过 `TINYINFER_VTC_WP`、`TINYINFER_VTC_WQ` 暴露为实验参数。

Day 2 显式启用 async scheduling。适配器对远端 KV connector、LoRA 和 speculative
decoding 继续 fail-fast，不能静默降级到 FCFS。`VTCScheduler` 继承 `AsyncScheduler`，
只覆盖 waiting queue 与生命周期计费 hook，禁止复制整份上游 `schedule()`。vLLM v0.29.0
的自定义 scheduler 提示不检查真实基类，因此使用仓库内最小日志补丁
`patches/vllm-v0.29.0-custom-async-scheduler-warning.patch`；该补丁不改变调度语义。

#### 5.3.2 本地单元测试和固定版本检查

```bash
cd /Users/yyu03/project/dev/vtc-infer
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
python -m compileall -q tinyinfer tests
```

测试至少覆盖：默认与自定义 `wp/wq` 计费、confirmed/pending service、多个 in-flight
batch、结算、取消、stale/重复回调、最小 counter 选择、租户 FIFO、counter lift、counter
单调性、相同 counter 的确定性排序、重复请求及非法参数。固定版本检查必须确认：

- `vllm.v1.core.sched.async_scheduler.AsyncScheduler` 仍通过 `_update_after_schedule`
  管理 output placeholder，并继承 `add_request`、`schedule`、`update_from_output` 和
  `finish_requests`；
- `Request.sampling_params.extra_args` 能读取 `tenant_id`；
- `SchedulerOutput.num_scheduled_tokens` 与 `EngineCoreOutputs.outputs[].new_token_ids`
  的语义未变化；
- `--scheduler-cls tinyinfer.scheduler.vllm_adapter.VTCScheduler` 能加载成功。

任一接口变化都先停止 GPU 实验并更新适配器；不能通过捕获异常回退 FCFS。

#### 5.3.3 同步代码并启动 VTC 服务

正式 GPU 验收只使用已提交 commit。先在 GPU 主机执行：

```bash
cd /workspace/vtc-infer
git pull --ff-only
git status --short
git rev-parse HEAD
. .venv/bin/activate
pytest -q
```

停止 FCFS 容器，使用同一镜像、模型 revision、缓存、端口及资源参数启动 VTC。这里把仓库
只读挂载并加入 `PYTHONPATH`，避免在容器内复制或手改 vLLM：

```bash
sudo docker stop tinyinfer-vllm-fcfs 2>/dev/null || true
sudo docker rm tinyinfer-vllm-fcfs 2>/dev/null || true

sudo docker run -d \
  --name tinyinfer-vllm-vtc \
  --gpus all \
  --ipc=host \
  -p 8000:8000 \
  -e PYTHONPATH=/workspace/vtc-infer \
  -e TINYINFER_VTC_WP=1 \
  -e TINYINFER_VTC_WQ=2 \
  -v /workspace/vtc-infer:/workspace/vtc-infer:ro \
  -v /data/tinyinfer/huggingface:/root/.cache/huggingface \
  -v /data/tinyinfer/vllm-cache:/root/.cache/vllm \
  vllm/vllm-openai:v0.29.0 \
  Qwen/Qwen2.5-1.5B-Instruct \
  --revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306 \
  --max-model-len 4096 \
  --max-num-seqs 16 \
  --enable-prefix-caching \
  --async-scheduling \
  --scheduler-cls tinyinfer.scheduler.vllm_adapter.VTCScheduler
```

异步 FCFS 对照把 scheduler class 改为
`tinyinfer.scheduler.vllm_adapter.CustomAsyncFCFSScheduler`，其他参数不变。若为制造持续排队
必须把 `max_num_seqs` 降到 8，则 FCFS 三次基线和 VTC 三次实验都要用 8 重跑，不能直接
比较不同设置。控制请求长度，出现 KV OOM 或频繁 preemption 时先降低输出长度或发压强度。

#### 5.3.4 VTC smoke test

```bash
sudo docker logs -f tinyinfer-vllm-vtc
curl --fail --silent http://127.0.0.1:8000/health
curl --fail --silent http://127.0.0.1:8000/v1/models | jq

curl --fail --no-buffer http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "messages": [{"role": "user", "content": "Reply with exactly: VTC ready"}],
    "temperature": 0,
    "max_tokens": 16,
    "stream": true,
    "stream_options": {"include_usage": true},
    "vllm_xargs": {"tenant_id": "smoke-tenant"}
  }'
```

随后发送两个不同 `tenant_id` 的并发短请求。验收要求：请求都有 `[DONE]` 和 usage；缺失
`tenant_id` 的请求归入保留的 `__default__` 租户（vLLM 0.29.0 中从 scheduler 抛错会杀死
EngineCore）；正式实验必须显式传入租户。日志没有 import error、deadlock、OOM、worker crash 或偷偷
切回默认 Scheduler。通过 `docker inspect` 保存环境变量和启动参数。

#### 5.3.5 运行三次 VTC 对照实验

每次运行前等待 waiting queue 回到 0，实验编号依次使用 `r1`、`r2`、`r3`：

```bash
TINYINFER_EXPERIMENT_ID=vtc-noisy-neighbor-seed20260912-r1

python -m scripts.run_experiment \
  --workload benchmark/workloads/noisy_neighbor.yaml \
  --policy vtc \
  --experiment-id "$TINYINFER_EXPERIMENT_ID" \
  --service-parameter max_model_len=4096 \
  --service-parameter max_num_seqs=16 \
  --service-parameter prefix_caching=true \
  --service-parameter async_scheduling=true \
  --service-parameter wp=1 \
  --service-parameter wq=2 \
  --service-parameter vllm_version=0.29.0 \
  --service-parameter vllm_image_digest=sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1 \
  --service-parameter model_revision=989aa7980e4cf806f80c7fef2b1adb7bc71aa306
```

另一个终端完全复用 5.2.5 的 waiting queue 采样，只把实验编号改为 VTC。实验结束后执行
5.2.6～5.2.7 的分析与数据完整性检查，并保存：

```bash
sudo docker logs tinyinfer-vllm-vtc \
  > "results/runs/${TINYINFER_EXPERIMENT_ID}/server.log" 2>&1
sudo docker inspect tinyinfer-vllm-vtc \
  > "results/runs/${TINYINFER_EXPERIMENT_ID}/container-inspect.json"
```

#### 5.3.6 FCFS/VTC 验收与当天退出条件

只比较同一 commit、模型、revision、镜像 digest、workload、seed、`max_num_seqs`、prefix
caching 和 async 设置的运行。三次重复均需满足：

- 单元测试全部通过；
- `failed_requests == 0`，请求数、request ID 和计划到达时间与 FCFS 对应重复一致；
- VTC 请求全部排空，无死锁、丢请求、counter 回退、OOM 或持续抢占；
- waiting queue 达到与 FCFS 相同的饱和门槛；
- 高频租户不能长期挤压持续活跃的低频租户；以 `tenant-b` P95/P99 TTFT、最长连续等待
  区间和完成时间线共同判断，不能只看 Jain index；
- aggregate throughput 无无法解释的异常下降；若下降，先核对 scheduler CPU、日志和
  preemption，再记录公平性与吞吐的权衡；
- FCFS/VTC 的唯一策略差异是 `scheduler_cls` 与明确记录的 `wp/wq`。

#### 5.3.7 2026-09-13 执行记录

- 已实现 `CustomAsyncFCFSScheduler(AsyncScheduler)` 和
  `VTCScheduler(AsyncScheduler)`；后者保留默认租户和既有 unsupported-feature fail-fast；
- 已实现 confirmed/pending service、批次 reservation、实际 output 结算、取消释放及重复/
  stale output 幂等行为；原有 counter lift、FIFO 和确定性排序保持通过；
- 固定镜像 digest、模型 revision、workload、seed、`max_num_seqs=16` 和 prefix caching，
  完成三次异步 FCFS 与三次异步 VTC；每轮均为 1989/1989、0 失败、无缺失 TTFT/usage、
  时间戳合法且日志无 traceback、OOM 或 worker crash；
- 三轮 VTC/FCFS 吞吐比分别为 99.06%、101.56%、101.63%；tenant-b P95 TTFT 比分别为
  11.27%、20.00%、21.85%；VTC dispatch-lag P95 分别为 1.70、1.68、1.79 ms；
- 原始请求、manifest、analysis、waiting queue、日志和 container inspect 保存在
  `results/remote/gpu1-20260913-async/`，汇总见
  `results/report/vtc-async-gpu-test-20260913.md`。

### 5.4 阶段 1B：缓存实验与 VTC-Miss（可选）

目标：在已完成的 async admission-fair VTC 基线上，验证 cache-miss-aware service 成本
是否能在共享前缀场景改善缓存利用率或有效吞吐，同时量化其对公平性、TTFT/TPOT 和调度
开销的影响。本阶段不阻塞阶段 1A 完成，也不包含 Kubernetes、Production Stack 或 KEDA。

开始前必须先定义 prefix hit、partial hit、miss 与抢占重算的计费规则，并确认 vLLM
v0.29.0 能稳定导出对应观测数据；否则停止在设计阶段，不实现名称存在但不可验证的策略。

- 增加共享长前缀和随机前缀两组 workload；
- 先在纯 Python 状态层测试成本公式、counter lift、取消、stale output 与多 in-flight batch，
  再实现并明确标记实验性的 VTC-Miss 成本模型；
- FCFS、VTC、VTC-Miss 各重复至少 3 次；
- 自动生成 Jain index、service gap、P50/P95/P99 TTFT、TPOT、吞吐和 cache hit 图表；
- 编写 `scripts/run_server.sh`、`scripts/run_experiment.sh` 和 `scripts/render_report.sh`；
- 完成 README、已知限制、复现命令和 3～5 分钟演示。

验收：三种策略使用相同异步执行路径和固定环境；每种策略三轮请求完整性检查通过；报告同时
呈现 locality 收益、公平性变化和吞吐代价；从干净 checkout 按 README 能重新运行至少一组
小规模实验。若没有稳定收益，应如实记录负结果，而不是调整 workload 追求正向结论。

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
- [ ] FCFS、VTC 策略实现与配置开关；VTC-Miss 仅作为可选研究扩展；
- [ ] 单元测试和镜像 smoke test；
- [ ] noisy-neighbor 与 prefix-reuse workload；
- [ ] 每种策略至少 3 次原始结果；
- [ ] 自动分析和绘图脚本；
- [ ] 单机启动、停止和复现实验命令；
- [ ] 候选镜像 tag、digest 和发布记录；
- [ ] README、限制说明和演示材料。

阶段一全部通过后，阶段二再增加 Production Stack Helm values、Router、Prometheus/Grafana、readiness 和回滚演练。

## 11. 阶段二目标、边界与退出条件

阶段二把阶段一已经验证的 async admission-fair VTC 交付成标准 Kubernetes 服务，回答：

```text
已提交代码 + 不可变镜像
→ Production Stack Helm 部署
→ Router 暴露 OpenAI-compatible API
→ FCFS / VTC 可配置切换
→ Prometheus / Grafana 可观测
→ Kubernetes 回归、Pod 重建和 Helm rollback
→ 证据回传本地
```

本阶段只交付一个模型副本并申请一张 GPU。以下内容明确不做：

- 不实施 KEDA、HPA 或第二个 vLLM 副本；
- 不宣称跨 Pod 或集群级 VTC 公平；
- 不把 VTC-Miss 作为阶段二门槛；
- 不增加 prefix-aware/KV-aware 路由，Router 固定使用 round-robin；
- 不承诺生产级 TLS、认证、多租户控制面或零停机单副本升级；
- 不改变阶段一算法参数来追求更好 Kubernetes 实验结果。

阶段二全部退出条件：

- 从干净 Git commit 构建并推送自定义 vLLM 镜像，部署使用完整 image digest；
- Production Stack Chart 版本、上游 commit、Chart 包 SHA256 和 Router 镜像 digest 已锁定；
- 一条命令可安装或升级，FCFS/VTC 只通过受版本管理的 values 切换；
- Router 的 `/v1/models`、流式请求、usage 和 `vllm_xargs.tenant_id` 全部正常；
- Pod 删除重建后模型重新 Ready，Router 恢复服务；不把单副本重建表述为零停机；
- Prometheus 能持续抓取 vLLM、Router 和 VTC-Infer 低基数指标，Grafana dashboard 可导入；
- Kubernetes 中的 FCFS/VTC 回归达到本节规定的数据完整性与性能门槛；
- 错误 scheduler 配置会使发布失败，不会静默回退到 FCFS；
- 至少完成一次可验证的 Helm upgrade 和 rollback，并在回滚后通过 API smoke test；
- Git SHA、镜像 digest、Chart 版本、values、Kubernetes 资源、指标、日志和实验数据已回传本地。

## 12. 阶段二目录与事实来源

阶段二实施时增加以下文件。大体积运行数据继续由 `.gitignore` 排除，只提交配置、脚本、
Dashboard 和最终报告：

```text
docker/
├── Dockerfile
└── build-info.env.example
deploy/
├── production-stack/
│   ├── chart.lock.yaml
│   ├── values-fcfs.yaml
│   ├── values-vtc.yaml
│   └── values-invalid-scheduler.yaml
└── monitoring/
    ├── values.yaml
    └── prometheus-rules.yaml
dashboards/
└── vtc-infer-overview.json
scripts/
├── build_image.sh
├── deploy_phase2.sh
├── smoke_test_k8s.sh
├── collect_phase2_evidence.sh
└── rollback_phase2.sh
docs/
├── upstream.md
└── phase2-runbook.md
results/
├── remote/gpu1-<date>-phase2/       # 不提交，大体积原始证据
└── report/phase2-gpu-test-<date>.md  # 提交，结论和关键数据
```

当前 `.gitignore` 中存在宽泛的 `docs/*` 规则。开始实现阶段二时应改为只忽略明确的本地草稿
或为上述交付文档增加例外，确认 `docs/upstream.md` 和 `docs/phase2-runbook.md` 能正常被
Git 跟踪；不要依赖 `git add -f` 长期维护正式文档。

事实来源按以下优先级管理：

1. `deploy/production-stack/chart.lock.yaml` 是上游版本事实来源；
2. `values-fcfs.yaml` 和 `values-vtc.yaml` 是部署参数事实来源；
3. Kubernetes 实际 Pod 的 `imageID`、args 和 env 是运行事实来源；
4. 请求级 JSONL 是租户 TTFT、完成率与公平性结论的事实来源；
5. Prometheus 是服务运行趋势的事实来源，不使用 `tenant_id` 或 `request_id` 作为 label；
6. 最终报告只引用能够追溯到上述原始证据的数据。

两个策略 values 必须是完整、可独立部署的文件。由于 `modelSpec` 是数组，不依赖多个 values
文件对数组元素进行隐式合并。增加配置测试，保证两个文件除 scheduler class、VTC 权重和
明确的策略标识外保持一致。

## 13. 阶段二开始门禁

### 13.1 先把阶段一结果固定到干净 commit

当前 2026-09-13 异步实验记录为 `git_dirty=true`，只能作为阶段一开发证据。进入阶段二前
必须从已提交版本重跑最终配对验收：

```bash
cd /Users/yyu03/project/dev/vtc-infer
git status --short
.venv/bin/pytest -q
git add <本次阶段一文件>
git commit -m "Finalize async admission-fair VTC"
git push origin main
git rev-parse HEAD

ssh gpu1
cd /workspace/vtc-infer
git fetch origin
git checkout <上一步完整 commit SHA>
git status --short
```

远端 `git status --short` 必须为空，再按 5.3 节运行三轮异步 FCFS/VTC。测试完成后把原始
数据同步回本地，并更新报告中的完整 commit SHA：

```bash
rsync -a gpu1:/workspace/vtc-infer/results/runs/<experiment-prefix>/ \
  /Users/yyu03/project/dev/vtc-infer/results/remote/gpu1-<date>-phase1-final/
```

只有干净提交上的结果通过阶段一门槛，才继续构建阶段二镜像。

### 13.2 锁定上游与工具版本

实施前填写 `chart.lock.yaml`，至少包含：

```yaml
production_stack:
  repository: https://github.com/vllm-project/production-stack.git
  chart_repository: https://vllm-project.github.io/production-stack
  chart: vllm-stack
  chart_version: "0.1.12"
  upstream_tag: "vllm-stack-0.1.12"
  upstream_commit: "66b60661aa3052810859a417559e9e830772a091"
  chart_archive_sha256: "a33248ff71c12b600774ec084c1d68e2a632d00132fc0f8b6cad4b52ca9eb0d3"
router:
  image: "lmcache/lmstack-router:v0.1.12@sha256:<resolved-digest>"
kubernetes:
  distribution: k3s
  version: "<exact-version>"
nvidia_device_plugin:
  chart_version: "<exact-version>"
monitoring:
  kube_prometheus_stack_chart_version: "82.4.3"
```

截至 2026-09-14，官方 Chart `0.1.12` 对应 tag `vllm-stack-0.1.12` 和上述 commit；其
`kube-prometheus-stack` dependency 为 `82.4.3`。执行时仍需重新下载发布包并核对 SHA256，
同时解析当前 amd64 Router 镜像 digest。不能把 `main`、`latest` 或未校验的教程默认值直接
写进正式部署。

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm repo update
helm pull vllm/vllm-stack \
  --version 0.1.12 \
  --destination /workspace/phase2-chart
echo 'a33248ff71c12b600774ec084c1d68e2a632d00132fc0f8b6cad4b52ca9eb0d3  /workspace/phase2-chart/vllm-stack-0.1.12.tgz' \
  | sha256sum --check
helm show chart vllm/vllm-stack --version 0.1.12
helm show values vllm/vllm-stack --version 0.1.12 \
  > /workspace/phase2-chart/upstream-values.yaml
```

正式 values 中必须覆盖上游默认的浮动镜像、示例模型、LoRA、LMCache、KEDA 和多卡参数。
禁止因为 Chart 默认值变化而意外启用未测试能力。

### 13.3 Kubernetes 与 GPU 预检

GPU 主机应至少保留 200Gi 磁盘，推荐 250Gi。先记录环境并确认 Docker 阶段一服务已经
停止，避免它占用唯一 GPU：

```bash
ssh gpu1
nvidia-smi
df -h /
sudo docker system df
sudo docker ps
kubectl version --client
helm version
```

`gpu1` 从阶段一切换到阶段二时，必须停止占用唯一 GPU 的裸 Docker 服务，并确认没有宿主机
compute process；只停止、不删除容器，阶段一环境仍可人工恢复：

```bash
sudo docker ps --no-trunc \
  --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'
sudo docker stop tinyinfer-vllm-custom-fcfs
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
```

最后一条命令必须没有输出。若仍有进程，先用 `pstree -aps <pid>` 和 `ps -fp <pid>` 查明
所有者，不得通过降低 `gpuMemoryUtilization` 掩盖其他服务占用 GPU。

阶段二默认使用固定版本的单节点 k3s。若机器已有可复用集群，则保留现有发行版，但必须把
版本与安装方式写入 `chart.lock.yaml`，不得在同一主机再安装第二套 Kubernetes。新建 k3s
时锁定 `INSTALL_K3S_VERSION`，不使用未记录版本：

```bash
VTC_K3S_VERSION=<exact-version>
curl -sfL https://get.k3s.io \
  | INSTALL_K3S_VERSION="$VTC_K3S_VERSION" sh -

sudo install -d -m 0700 -o "$(id -u)" -g "$(id -g)" /workspace/.kube
sudo install -m 0600 -o "$(id -u)" -g "$(id -g)" \
  /etc/rancher/k3s/k3s.yaml /workspace/.kube/vtc-infer-config
export KUBECONFIG=/workspace/.kube/vtc-infer-config
kubectl get nodes -o wide
kubectl get runtimeclass
```

按固定版本安装 NVIDIA device plugin，并先用独立 CUDA Pod 验证 `nvidia.com/gpu: 1`。
GPU smoke Pod 必须成功运行 `nvidia-smi`；随后确认节点 allocatable GPU 为 1：

```bash
kubectl get node -o json \
  | jq '.items[].status.allocatable["nvidia.com/gpu"]'
kubectl describe node | sed -n '/Capacity:/,/System Info:/p'
```

若 RuntimeClass、device plugin 或 GPU smoke 任一失败，停止在基础设施层，不开始 Helm
部署。GPU plugin 安装清单、版本和 smoke Pod YAML 都保存在 `results/remote/.../environment/`。

#### 13.3.1 `gpu1` 单节点实际安装步骤

本仓库提供 `scripts/install_phase2_cluster.sh` 固定安装 k3s `v1.36.4+k3s1`、Helm
`v3.22.0`、NVIDIA device plugin `0.20.0` 和本地 registry `registry:2.8.3`。脚本需要 sudo，
但不要用 `sudo ./scripts/...` 整体执行；整体 sudo 会把 kubeconfig 和 Helm repo 写成 root
所有，后续普通用户无法读取。按下列方式执行：

```bash
ssh gpu1
cd /workspace/vtc-infer
./scripts/install_phase2_cluster.sh
export KUBECONFIG=/workspace/.kube/vtc-infer-config
```

`gpu1` 的 Docker daemon 已配置两个 Docker Hub mirror。k3s 使用独立的 containerd，不会
继承 `/etc/docker/daemon.json`，因此脚本会写入：

```yaml
# /etc/rancher/k3s/registries.yaml
mirrors:
  "docker.io":
    endpoint:
      - "https://docker.1ms.run"
      - "https://docker.xuanyuan.me"
  "localhost:5000":
    endpoint:
      - "http://127.0.0.1:5000"
```

修改该文件后必须 `sudo systemctl restart k3s` 并重新等待 Node Ready。若事件包含
`failed to pull rancher/mirrored-pause` 与 Docker Hub timeout，优先核对上述 containerd
mirror；不要反复删除 Pod。

当前 GPU 节点没有安装 NFD，NVIDIA device plugin `0.20.0` 默认 affinity 因缺少
`feature.node.kubernetes.io/pci-10de.present` 而产生 `DESIRED=0`。单节点已由
`nvidia-smi` 人工确认是 NVIDIA GPU 后，安装脚本显式添加 `nvidia.com/gpu.present=true`
并以 `--set-json 'affinity={}'` 部署 DaemonSet。多节点环境不能照搬空 affinity，应安装 NFD
或只给已验真的 GPU 节点加标签。

```bash
kubectl -n nvidia-device-plugin get daemonset,pods -o wide
kubectl -n nvidia-device-plugin logs daemonset/nvidia-device-plugin --tail=120
kubectl get node -o json \
  | jq '.items[].status.capacity["nvidia.com/gpu"], .items[].status.allocatable["nvidia.com/gpu"]'
kubectl logs vtc-infer-gpu-smoke
```

验收值必须为 capacity/allocatable 均等于 `"1"`，smoke 日志能看到 RTX 4090。Pod 早期的
`Insufficient nvidia.com/gpu` 事件可以保留作排障证据，但最终 Pod 必须为 `Completed`。

## 14. Day 4：不可变镜像与 Production Stack 部署

### 14.1 构建并发布阶段二镜像

按第 7～9 节实现镜像打包，正式镜像必须：

- 以固定 digest 的 `vllm/vllm-openai:v0.29.0` 为基础；
- 安装当前 commit 构建出的 VTC-Infer wheel，不在 Pod 中挂载源码；
- 应用并校验仓库内最小 vLLM 日志补丁；
- 确保 `vllm` 可执行文件位于 PATH；官方 Chart 对非 LMCache 镜像执行 `vllm serve`；
- 写入 OCI revision/version/source label 和 `/opt/vtc-infer/build-info.json`；
- 同时包含 `CustomAsyncFCFSScheduler` 与 `VTCScheduler`；
- 默认不携带凭据、模型权重或本地实验数据。

本地单元测试通过后先提交，再到 GPU 主机构建、smoke、推送并取得 registry digest。正式
部署镜像格式为 `repository:immutable-tag@sha256:digest`，不能只使用 tag。

`gpu1` 没有外部 registry 登录，本次验收使用脚本创建的节点本地 registry。它是单节点测试
环境的交付 seam，不是生产 registry：

```bash
export VTC_IMAGE_REPOSITORY=localhost:5000/vtc-infer-vllm
./scripts/build_image.sh | tee results/remote/gpu1-<date>-phase2/image/build.log
```

脚本只允许干净 worktree，tag 包含版本和 12 位 Git SHA，推送后打印 manifest digest。
Production Stack values 使用形如：

```text
repository = localhost:5000/vtc-infer-vllm
tag = 0.2.0-<git-sha>@sha256:<manifest-digest>
```

基础镜像没有 `python` 命令，只有 `python3`；Dockerfile 必须使用 `python3`。基础镜像也已经
预装 `/usr/bin/patch`，只验证并使用它，不能执行 `apt-get purge --auto-remove patch`，否则
会连带删除 CUDA nvcc、编译器等基础镜像组件。

镜像 smoke 除第 8 节项目外，还要检查：

```bash
vllm --version
python -c 'from tinyinfer.scheduler.vllm_adapter import CustomAsyncFCFSScheduler, VTCScheduler'
cat /opt/vtc-infer/build-info.json
```

正式 GPU smoke 使用：

```bash
sudo docker run --rm --gpus all --entrypoint /bin/sh <image:tag> -c '
  nvidia-smi -L
  vllm --version
  cat /opt/vtc-infer/build-info.json
  python3 -c "from tinyinfer.scheduler.vllm_adapter import VTCScheduler"
'
```

不要用 `import vllm._C` 作为 vLLM 0.29.0 镜像验收：该版本的扩展是多个独立 `.abi3.so`
模块，并不提供名为 `vllm._C` 的统一 Python module。真正的 GPU kernel 可用性由服务启动、
模型加载和推理 smoke 验证。

分别启动 FCFS/VTC 后查询 `/metrics`，确认 vLLM 指标存在；若本阶段实现了自定义指标，
同时确认 `vtc_infer_` 前缀指标存在。任何 import error、补丁应用失败或 scheduler 静默回退
都阻断发布。

### 14.2 编写并静态验证 Helm values

`values-fcfs.yaml` 与 `values-vtc.yaml` 都显式固定以下内容：

- `servingEngineSpec.modelSpec[0].repository/tag`：自定义镜像的 immutable tag + digest；
- `modelURL` 与 `modelRevision`：阶段一相同模型和 revision；
- `replicaCount: 1`，使用完整 `resources` 同时声明 request/limit 各一张 `nvidia.com/gpu`；
- vLLM V1、`maxModelLen=4096`、`maxNumSeqs=16`、prefix caching 和相同内存参数；
- FCFS 使用 `CustomAsyncFCFSScheduler`，VTC 使用 `VTCScheduler` 且设置 `wp=1`、`wq=2`；
- 两种策略均显式启用 async scheduling；
- LoRA、LMCache、KEDA、Ray、speculative decoding 全部关闭；
- Router 启用、单副本、round-robin，Router 镜像使用固定 digest；
- 使用 PVC 或已记录的 hostPath 保存 Hugging Face 模型缓存；
- startup/readiness/liveness probe 都检查 `/health`，startup probe 要覆盖模型冷启动窗口；
- Service 类型默认 `ClusterIP`，通过 port-forward 做阶段二验收，不直接暴露公网 NodePort。

单 GPU、单副本 Engine 必须显式设置 `servingEngineSpec.strategy.type: Recreate`。上游默认
`RollingUpdate(maxSurge=100%, maxUnavailable=0)` 会先创建新 Pod，但新旧 Pod 都申请唯一
GPU，导致新 Pod 一直 Pending、旧 Pod 又不退出。`Recreate` 会先终止旧 Engine，再启动新
Engine；策略切换和回滚期间存在模型重载窗口，不能表述为零停机。Router readiness 和后端
发现必须如实反映这段不可用时间。

`resources` 与 `requestGPU/requestGPUType` 两套写法只选一套；本项目选择完整 `resources`。
如果 `kubectl get runtimeclass` 没有 `nvidia`，则把 `runtimeClassName` 显式设为空字符串。不得
设置 `vllmConfig.v0: "1"`，因为 Chart 会据此注入 `VLLM_USE_V1=0`。

Router 镜像首次启动时 Python import 和 Kubernetes discovery 初始化在 `gpu1` 上超过了 Chart
默认约 15 秒的 startup probe 容错窗口。因此三个 values 文件统一覆盖
`routerSpec.startupProbe` 为 `initialDelaySeconds=5`、`periodSeconds=5`、
`failureThreshold=12`，提供约 60 秒窗口。此调整不改变 readiness 语义；Router 只有
`/health` 成功后才加入 Service endpoint。

注意：官方 Chart 当前按 `repository:tag` 拼接镜像，digest 应放进 `tag`，形成合法的
`repository:tag@sha256:digest`。每次选版都通过实际模板确认，不能假设未来 Chart 保持这一
实现。

每次部署前必须通过静态门禁：

```bash
helm lint /workspace/phase2-chart/vllm-stack-0.1.12.tgz \
  -f deploy/production-stack/values-fcfs.yaml

helm template vtc-infer vllm/vllm-stack \
  --version 0.1.12 \
  --namespace vtc-infer \
  -f deploy/production-stack/values-fcfs.yaml \
  > /workspace/phase2-chart/rendered-fcfs.yaml

helm template vtc-infer vllm/vllm-stack \
  --version 0.1.12 \
  --namespace vtc-infer \
  -f deploy/production-stack/values-vtc.yaml \
  > /workspace/phase2-chart/rendered-vtc.yaml
```

检查渲染结果中只有一个 engine Deployment、一个 Router Deployment，engine 申请一张
GPU，镜像含 digest，参数含正确 scheduler class，且不存在 KEDA/HPA、LMCache、LoRA 或
第二个模型。把渲染结果保存为本次证据，但不提交其中可能存在的 Secret。

Router 固定使用 `lmcache/lmstack-router:v0.1.12`。在网络稳定时先用 Docker 拉取、记录原始
RepoDigest，再原样 tag/push 到 `localhost:5000/vtc-infer-router`，部署使用本地 repository
和同一 manifest digest，避免 containerd 在 Helm install 期间再次依赖公网：

```bash
sudo docker pull lmcache/lmstack-router:v0.1.12
sudo docker image inspect lmcache/lmstack-router:v0.1.12 \
  --format '{{index .RepoDigests 0}}'
sudo docker tag lmcache/lmstack-router:v0.1.12 \
  localhost:5000/vtc-infer-router:v0.1.12
sudo docker push localhost:5000/vtc-infer-router:v0.1.12
```

本地转存后的阶段二环境变量为：

```bash
export VTC_ROUTER_REPOSITORY=localhost:5000/vtc-infer-router
export VTC_ROUTER_TAG=v0.1.12@sha256:d8cfaf022f0179ba3f9d2bbcb95c602bd639b700f7a6ac409626758d1a366483
```

若直连拉取超过 10 分钟且没有 layer 进度，终止该次拉取并改用已配置 mirror 或 containerd
拉取；不要并发启动多个相同 pull。最终仍需保存 source tag、source digest、本地 registry
digest 和镜像架构，四者一致后才部署。

### 14.3 首次安装 FCFS

先部署 FCFS 作为 Kubernetes 基线：

```bash
export KUBECONFIG=/workspace/.kube/vtc-infer-config
kubectl create namespace vtc-infer --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install vtc-infer vllm/vllm-stack \
  --version 0.1.12 \
  --namespace vtc-infer \
  --create-namespace \
  --atomic \
  --timeout 20m \
  -f deploy/production-stack/values-fcfs.yaml

kubectl -n vtc-infer get pods,deploy,svc,pvc -o wide
kubectl -n vtc-infer rollout status deployment/<engine-deployment> --timeout=20m
kubectl -n vtc-infer rollout status deployment/<router-deployment> --timeout=5m
helm -n vtc-infer status vtc-infer
helm -n vtc-infer get values vtc-infer --all
helm -n vtc-infer get manifest vtc-infer
```

#### 14.3.1 `gpu1` 首次安装失败与修复记录（2026-09-14）

第一次实际安装使用 `scripts/deploy_phase2.sh fcfs`、`--atomic --timeout 30m`。故障现场通过
以下命令保留，后续遇到 Pod 重启时也按相同顺序排查：

```bash
export KUBECONFIG=/workspace/.kube/vtc-infer-config
helm -n vtc-infer status vtc-infer
kubectl -n vtc-infer get pods -o wide
kubectl -n vtc-infer get events --sort-by=.lastTimestamp
kubectl -n vtc-infer logs -l app.kubernetes.io/component=serving-engine \
  --all-containers --previous --tail=400
kubectl -n vtc-infer logs -l app.kubernetes.io/component=router \
  --all-containers --previous --tail=400
kubectl -n vtc-infer get deploy \
  vtc-infer-qwen25-15b-deployment-vllm vtc-infer-deployment-router -o yaml
```

Engine 日志的根因是 `Free memory ... 1.21/23.52 GiB`，而期望值为 21.17 GiB。宿主机
`nvidia-smi` 和 `pstree` 定位到阶段一容器 `tinyinfer-vllm-custom-fcfs` 占用 22444 MiB；按
13.3 节停止它后，Kubernetes Engine 成功加载同一模型 revision、完成 CUDA graph warmup，
并以 `CustomAsyncFCFSScheduler` 开始监听 8000 端口。冷 PVC 首次访问 Hugging Face 曾发生两次
约 130 秒超时，但随后权重下载成功；startup probe 的 15 分钟窗口足以覆盖该过程。

Router 容器日志显示应用本身能启动并返回 `/health=200`，但 Chart 默认 startup probe 窗口
过短，先前已被 kubelet 多次终止。values 已按 14.2 节扩窗。

同一次安装中还有与核心服务无关的监控镜像故障：
`registry.k8s.io/kube-state-metrics:v2.18.0` 解析到 Google Artifact Registry 后连接超时，
node-exporter 拉取也长期停留在 `ContainerCreating`。阶段二只要求采集 Engine、Router 和
VTC-Infer 指标，因此固定关闭 kube-state-metrics、node-exporter、Alertmanager 和默认
Kubernetes 规则，只保留 Prometheus Operator、Prometheus、Grafana、自定义 ServiceMonitor
和 `deploy/monitoring/prometheus-rules.yaml`。对应 values 为：

```yaml
kube-prometheus-stack:
  enabled: true
  defaultRules:
    create: false
  alertmanager:
    enabled: false
  kubeStateMetrics:
    enabled: false
  nodeExporter:
    enabled: false
```

这不是通用生产监控配置；若要监控节点和 Kubernetes 对象，应为目标环境建立可达的镜像
仓库后重新启用，不得声称本阶段已经覆盖这些指标。

`<engine-deployment>` 和 `<router-deployment>` 从实际渲染结果取得，不在脚本中按模糊名称
猜测。检查 engine Pod 的 `imageID`、args、env、GPU limit 和 probe，确认运行状态与 values
一致。

### 14.4 通过 Router 验收 API

只访问 Router，不绕过 Router 直接把 engine API 当作阶段二成功证据：

终端 A：

```bash
kubectl -n vtc-infer port-forward svc/vtc-infer-router-service 30080:80
```

终端 B：

```bash
curl --fail --silent http://127.0.0.1:30080/v1/models | jq
```

随后发送带 `vllm_xargs.tenant_id` 的流式 chat completion，并保存完整 SSE。验收：

- `/v1/models` 返回固定模型；
- 流式响应包含首 token、`[DONE]` 和非空 usage；
- Router 与 engine 日志没有 5xx、import error、OOM 或 worker crash；
- 实际 engine args 显示 `CustomAsyncFCFSScheduler` 与 async scheduling；
- Pod 使用的镜像 `imageID` 与锁定 digest 一致。

### 14.5 切换到 VTC 并验证错误配置 fail-fast

使用 VTC values 创建下一个 Helm revision：

```bash
helm upgrade vtc-infer vllm/vllm-stack \
  --version 0.1.12 \
  --namespace vtc-infer \
  --atomic \
  --timeout 20m \
  -f deploy/production-stack/values-vtc.yaml
```

等待 rollout 完成后重复 Router smoke，确认实际 args 和 env 为 `VTCScheduler`、`wp=1`、
`wq=2`。FCFS/VTC 切换不得通过进入 Pod 手工改文件完成。

再用 `values-invalid-scheduler.yaml` 或脚本注入不存在的 scheduler class，确认发布失败且
engine 日志明确报错，Router 不会把它识别成健康 FCFS 后端。这个故障演练不使用
`--atomic`，以便在超时后保存失败 Pod 的 events 和日志；取证完成后立即 `helm rollback`
到演练前记录的健康 revision，并重新执行 Router smoke。不得把故障配置留作最终状态。

Day 4 退出条件：

- FCFS 和 VTC 都能从同一不可变镜像通过 values 独立部署；
- API 只经 Router 验收且流式响应完整；
- Pod 重建、探针和模型缓存行为符合设计；
- 错误 scheduler 配置 fail-fast；
- 所有实际运行参数与锁定文件一致。

## 15. Day 5：Prometheus、Grafana 与自定义指标

### 15.1 监控部署选择

一个集群只保留一套 Prometheus/Grafana。若 GPU 主机没有现成 Prometheus Operator，本阶段
采用 Production Stack Chart 内置的 `kube-prometheus-stack` 依赖，并锁定其 dependency
版本；不要同时再安装第二套 monitoring release。values 至少启用：

```yaml
servingEngineSpec:
  serviceMonitor:
    enabled: true
routerSpec:
  serviceMonitor:
    enabled: true
grafanaDashboards:
  enabled: true
kube-prometheus-stack:
  enabled: true
prometheus-adapter:
  enabled: false
```

内置 Prometheus 的 `serviceMonitorSelector` 固定选择
`app.kubernetes.io/part-of=vllm-stack`。不要在 `servingEngineSpec.labels` 中覆盖这个 Chart
保留标签；项目身份使用 `app.kubernetes.io/instance=vtc-infer`，策略使用
`vtc-infer-policy=fcfs|vtc`。本次首次安装后的静态复查曾发现 Engine 将 `part-of` 覆盖成
`vtc-infer`，渲染结果会使 Prometheus 只能选择 Router ServiceMonitor，已在正式重装前移除
该覆盖并加入配置测试。

`prometheus-adapter` 和 KEDA 属于阶段三，本阶段保持关闭。如果集群已有监控栈，则把内置
`kube-prometheus-stack` 设为 false，并为 engine/router ServiceMonitor 添加现有 Prometheus
实际选择的低基数 label；选择结果和原因写入 `docs/phase2-runbook.md`。

### 15.2 指标契约

先直接保存 engine 与 Router `/metrics` 输出，建立实际指标清单，再编写 PromQL 和
Dashboard。不得根据其他 vLLM 版本的名字猜测指标。阶段二必须覆盖：

- waiting/running requests；
- TTFT 和端到端请求延迟分布；
- prompt/generation token throughput；
- prefix cache hit 或 KV cache usage；
- 请求成功/失败或 finished requests；
- Router QPS、后端健康与请求延迟；
- 当前部署策略、Pod Ready 状态与重启次数（本阶段由 Helm values、`kubectl` 状态和事件取证，
  不启用 kube-state-metrics）。

租户级 TTFT 和公平性继续从请求级 JSONL 计算，不把 `tenant_id`、`request_id`、
`experiment_id` 放入 Prometheus label。

阶段二增加以下低基数自定义指标；若固定版本 vLLM 的 multiprocess registry 无法可靠导出，
必须在报告中说明并删除对应 Dashboard 面板，不能伪造数据：

```text
vtc_infer_scheduler_decisions_total{policy,reason}
vtc_infer_scheduler_selection_seconds{policy}
vtc_infer_active_tenants{policy}
vtc_infer_service_gap{policy}
vtc_infer_build_info{version,git_sha}
```

其中 `reason` 必须是代码中固定枚举；`service_gap` 定义为当前活跃租户 effective counter 的
最大值减最小值；selection 指标只测 VTC 选择 hook，不冒充整个 vLLM schedule 开销。
增加单元测试验证指标注册、更新、label 集合和无高基数 label。

### 15.3 Prometheus 验收

启动 port-forward 后查询 targets 和固定 PromQL。port-forward 保持在终端 A，查询命令在
终端 B 执行：

```bash
kubectl -n vtc-infer get servicemonitor
kubectl -n vtc-infer port-forward svc/vtc-infer-kube-prometheus-stack-prometheus 9090:9090

curl --fail --silent http://127.0.0.1:9090/api/v1/targets \
  > results/remote/gpu1-<date>-phase2/prometheus/targets.json
curl --fail --get --silent http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=up' \
  > results/remote/gpu1-<date>-phase2/prometheus/up.json
```

Service 名称从实际 `kubectl get svc` 取得。验收要求：engine 和 Router target 均为 `up=1`，
连续产生测试请求后 waiting、running、TTFT、throughput 指标均出现非空样本；自定义指标若
列为交付项，也必须能从 Prometheus 查询到，而不是只在进程日志中出现。

### 15.4 Grafana dashboard 验收

`dashboards/vtc-infer-overview.json` 只使用已经验证存在的指标，至少包含：

- 服务健康、当前策略与镜像版本；
- Router QPS/错误与后端健康；
- waiting/running requests；
- P50/P95/P99 TTFT 和端到端延迟；
- prompt/generation throughput；
- KV cache usage/cache hit；
- scheduler selection overhead、active tenants 和 service gap（指标可用时）。

Dashboard JSON 必须进入 Git。通过 ConfigMap 自动加载或可复现导入，不能只保留浏览器中的
临时面板。保存 Dashboard 截图、导出的 JSON、Grafana 数据源状态和一段带负载时间范围的
面板证据。

## 16. Day 5：Kubernetes 回归、重建与回滚

### 16.1 FCFS/VTC 配对回归

通过 Router endpoint 运行阶段一相同的 noisy-neighbor workload。FCFS 与 VTC 各运行三轮，
保持 commit、镜像 digest、Chart 版本、模型 revision、workload、seed、vLLM 参数和 Pod
资源完全一致；每次切换策略后等待 Pod Ready、队列归零并完成一次 warm-up。

每轮除阶段一产物外，还保存：

- `helm get values --all` 与 `helm get manifest`；
- Pod YAML、`imageID`、events 和 rollout 状态；
- engine/Router 日志；
- Prometheus 对应实验时间窗口的查询结果；
- 当前策略、Helm revision、Chart 版本和 Router endpoint；
- 客户端所在位置与到 Router 的网络路径。

回归硬门槛：

- 每轮 1989/1989 请求完成，失败、缺失 first-token、缺失 usage、非法时间戳均为 0；
- dispatch-lag P95 小于 100 ms，确认客户端没有成为瓶颈；
- waiting queue 形成与阶段一一致的饱和区间；
- 三轮 VTC 吞吐分别达到对应 Kubernetes FCFS 的 90% 以上；
- 三轮低频租户 P95 TTFT 分别低于对应 Kubernetes FCFS 的 50%；
- 日志无 traceback、OOM、worker crash 或 scheduler 静默回退；
- 若同策略 Kubernetes 与裸机吞吐或尾延迟偏差超过 10%，必须调查 Router、CPU、网络、
  metrics scrape 和容器资源；超过 15% 且无法解释时，阶段二不通过。

简历中的 99.06%～101.63% 和 11.27%～21.85% 仍引用阶段一干净提交上的配对结果；阶段二
Kubernetes 数字单独报告，不能混用两套环境中更好看的结果。

### 16.2 Pod 重建与 readiness

记录删除前的 Pod、PVC 和镜像信息，然后删除 engine Pod，由 Deployment 自动重建：

```bash
kubectl -n vtc-infer get pods,pvc -o wide
kubectl -n vtc-infer delete pod <engine-pod>
kubectl -n vtc-infer get pods -w
kubectl -n vtc-infer rollout status deployment/<engine-deployment> --timeout=20m
```

记录 Pod 删除、重新调度、镜像启动、模型加载、Ready 和 Router 首次成功请求的时间。验证
PVC/缓存仍存在，Router 在 backend 未 Ready 时不向其发送正常流量，恢复后流式请求成功。
单副本重建期间允许不可用，但必须被 readiness 和 Router 健康状态如实反映。

### 16.3 Helm upgrade 与 rollback

至少保留两个健康 revision：revision A 使用 FCFS values，revision B 使用 VTC values。
确认 B 正常后执行：

```bash
helm -n vtc-infer history vtc-infer
helm -n vtc-infer rollback vtc-infer <revision-a> --wait --timeout 20m
kubectl -n vtc-infer rollout status deployment/<engine-deployment> --timeout=20m
helm -n vtc-infer get values vtc-infer --all
```

回滚后必须检查：

- 实际 scheduler class、环境变量、镜像 `imageID` 和 Helm revision 已恢复；
- Router `/v1/models` 与带 usage 的流式请求成功；
- Prometheus targets 恢复 `up=1`，Grafana 无持续数据断层；
- 日志无配置漂移、CrashLoopBackOff 或静默 FCFS fallback；
- 回滚开始、Pod Ready、Router 恢复的时间线已保存。

若需要把最终环境恢复为 VTC，再使用已提交的 `values-vtc.yaml` 执行一次显式 `helm upgrade`，
不要在 Pod 内手工修改。

## 17. 证据回传、报告与阶段二交付清单

### 17.1 收集证据

远端目录统一为：

```text
results/remote/gpu1-<date>-phase2/
├── environment/
├── image/
├── helm/
├── kubernetes/
├── smoke/
├── prometheus/
├── grafana/
├── experiments/
└── rollback/
```

`scripts/collect_phase2_evidence.sh` 只能收集非敏感信息。禁止导出 Kubernetes Secret、
registry credential、HF token、完整 kubeconfig 或 Grafana admin 密码。收集完成后，从本地
执行：

```bash
rsync -a gpu1:/workspace/vtc-infer/results/remote/gpu1-<date>-phase2/ \
  /Users/yyu03/project/dev/vtc-infer/results/remote/gpu1-<date>-phase2/
```

在本地从同步后的 JSONL 重新生成分析，编写
`results/report/phase2-gpu-test-<date>.md`。报告至少包含：环境锁、部署架构、两种策略的
三轮结果、Prometheus targets、Pod 重建时间线、Helm rollback 时间线、已知限制和证据路径。

### 17.2 最终复核

```bash
cd /Users/yyu03/project/dev/vtc-infer
.venv/bin/pytest -q
git status --short
git diff --check
```

此时 `git status --short` 应只包含计划中的阶段二交付物。确认报告没有密钥和未经证据支持的
结论后提交，再验证工作区为空。阶段二完成标签建议使用：

```bash
git add <阶段二交付文件>
git commit -m "Deliver observable Production Stack deployment"
git status --short
git tag -a v0.2.0 -m "VTC-Infer phase-2 observable deployment"
git push origin main
git push origin v0.2.0
```

### 17.3 阶段二交付清单

- [ ] 阶段一最终实验来自干净 commit，数据已回传本地；
- [ ] 自定义镜像可同时运行 FCFS/VTC，tag、digest 和 build info 已记录；
- [ ] Production Stack Chart、上游 commit、Router 镜像和依赖版本已锁定；
- [ ] FCFS/VTC 两份 values 通过 lint、template 和配置差异测试；
- [ ] 单节点 Kubernetes 可分配一张 GPU，GPU smoke Pod 通过；
- [ ] Router OpenAI-compatible API、流式响应和 tenant_id 传递通过；
- [ ] 错误 scheduler 配置 fail-fast，未静默回退；
- [ ] engine/Router ServiceMonitor target 均为 up；
- [ ] Grafana dashboard 已版本管理并展示真实负载窗口；
- [ ] Kubernetes FCFS/VTC 各三轮回归达到硬门槛；
- [ ] Pod 删除重建、readiness 和模型缓存恢复已验证；
- [ ] Helm upgrade/rollback 后 API 与监控恢复；
- [ ] Git SHA、镜像/Chart digest、values、日志、指标和实验原始数据已回传；
- [ ] 阶段二报告、README、`docs/upstream.md` 和限制说明已更新；
- [ ] 工作区干净并创建 `v0.2.0` 标签。

只有以上清单全部通过，简历中才可以写“通过 Production Stack 与 Helm 部署单 GPU 服务并
支持 FCFS/VTC 策略切换；接入 Prometheus/Grafana 监控和版本回滚流程”。
