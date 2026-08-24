# 共享实验平台部署与验收手册

本目录只交付两个彼此隔离的单文件实验单元：

- `shared_evidence_decision_lab.py`：只在 `snowsong.top` 的 CPU 公网机运行；
- `gliner_entity_lab.py`：只在项目腾讯云 GN7 GPU 节点运行，由 GPU 主动建立反向 SSH 隧道。

两个进程都只监听回环地址。仓库不会生成或上传“完整项目包”，部署时只逐个暂存本手册列出的单文件。

## 0. 不可跳过的授权闸门

在任何远程写操作前，必须同时满足：

1. `snowsong.top` 所有者书面同意安装 Nginx 片段、systemd 服务和专用隧道用户；
2. 项目腾讯云账号负责人确认 GN7 购买、地域、库存和购买页价格；
3. 将实例、100 GB 磁盘及公网流量的准确单价填入 `tencent-gpu-purchase.example.json` 的副本并确认；
4. 成员提供 3–5 条真实 GLiNER 样本及精确期望跨度。

未取得授权时，只允许本地测试和远端只读探测；不得购买实例或修改服务器。

2026-08-16 的只读预检结果：`snowsong.top` 为 Debian、2 vCPU、1973 MiB 内存、
available 1497 MiB、无 swap、系统盘可用 46 GiB；80/443/22 对外，现有应用只监听
`127.0.0.1:8765`，没有 GPU。当前 `lgy` 会话对 `/etc/nginx` 和
`/etc/systemd/system` 均无写权限，且没有所有者部署授权，因此本次交付没有改动远端。

## 1. 本机验证 CPU 实验台

当前 Windows 机器的 `py` 和 `python` 均不在 `PATH`；不要照搬依赖 Python Launcher 的
`py -3.12` 命令。使用已经验证的 CPython 3.12.13 解释器，或复用现有 `.venv-lab`：

```powershell
$python312 = "C:\Users\卢冠宇\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $python312)) { throw "找不到固定的 CPython 3.12.13" }
if ((& $python312 --version) -ne "Python 3.12.13") { throw "CPython 版本不匹配" }
& $python312 -m venv .venv-lab
.venv-lab\Scripts\python.exe -m pip install pip==25.1.1 streamlit==1.60.0
$env:LAB_SHARED_PASSWORD="仅供本机验收的长随机密码"
.venv-lab\Scripts\python.exe -m streamlit run shared_evidence_decision_lab.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8501 --server.baseUrlPath AgentDemo/lab
```

浏览器打开 `http://127.0.0.1:8501/AgentDemo/lab/`。只上传成员定义的 3–5 条
JSON、JSONL 或 CSV 样本；任一预期不满足时脚本直接报断言并保留逐条中间结果。

Windows 项目路径若含中文，GLiNER 脚本会把公开 DeBERTa 配置和 SentencePiece 词表复制到
`C:\Temp\yanhai-gliner-tokenizer`。它不复制 GLiNER 主权重；可用
`GLINER_ASCII_TOKENIZER_DIR` 改成其他可写的纯 ASCII 目录。

## 2. 授权后的单文件远端暂存

只有第 0 节闸门通过后才执行。本机通过 FlClash 时，SSH/SCP 显式绑定物理 WLAN 地址
`192.168.1.10`；若网络变化，先重新只读确认物理地址。`<ubuntu@GN7_PUBLIC_IP>` 必须替换
为负责人提供的短期管理入口。

```powershell
$bindAddress = "192.168.1.10"
$publicSsh = "lgy@118.89.113.212"
$gpuSsh = "<ubuntu@GN7_PUBLIC_IP>"
ssh -o "BindAddress=$bindAddress" $publicSsh "install -d -m 0700 /tmp/yanhai-labs-deploy"
scp -o "BindAddress=$bindAddress" shared_evidence_decision_lab.py deploy/labs/evidence.env.example deploy/systemd/yanhai-evidence-lab.service deploy/nginx/agentdemo-labs.locations.conf "${publicSsh}:/tmp/yanhai-labs-deploy/"
ssh -o "BindAddress=$bindAddress" $gpuSsh "install -d -m 0700 /tmp/yanhai-labs-deploy"
scp -o "BindAddress=$bindAddress" gliner_entity_lab.py deploy/labs/gliner.env.example deploy/labs/tunnel.env.example deploy/labs/tencent-gn7-env.json deploy/systemd/yanhai-gliner-lab.service deploy/systemd/yanhai-gliner-tunnel.service "${gpuSsh}:/tmp/yanhai-labs-deploy/"
```

分别在两台机器执行 `sha256sum /tmp/yanhai-labs-deploy/*`，与本地
`Get-FileHash -Algorithm SHA256` 结果核对后再安装。`/tmp/yanhai-labs-deploy` 只是可审计的
暂存区；以下远端命令全部使用绝对路径，不依赖当前工作目录。

## 3. 授权后部署 CPU 公网面板

先记录空闲内存。连续运行时若 available 低于 512 MiB 或日志出现 OOM，停止服务并把公网机
升级到 4 GiB：

```bash
free -m
journalctl -k --since "24 hours ago" | grep -i -E "oom|out of memory" || true
```

运行时必须精确为服务器已经提供的 CPython 3.13.5；不满足就停止，不自行换版本：

```bash
test "$(python3 --version)" = "Python 3.13.5" || { python3 --version; echo "CPython 版本不匹配" >&2; exit 1; }
python3 -c "import venv; print('VENV_OK')"
id yanhai-lab >/dev/null 2>&1 || sudo useradd --system --home /var/lib/yanhai-evidence-lab --shell /usr/sbin/nologin yanhai-lab
sudo install -d -o root -g root /opt/yanhai-labs/evidence/releases/0.1.0
sudo install -m 0644 /tmp/yanhai-labs-deploy/shared_evidence_decision_lab.py /opt/yanhai-labs/evidence/releases/0.1.0/
sudo ln -sfn /opt/yanhai-labs/evidence/releases/0.1.0 /opt/yanhai-labs/evidence/current
sudo python3 -m venv /opt/yanhai-labs/evidence/venv
sudo /opt/yanhai-labs/evidence/venv/bin/python -m pip install pip==25.1.1 streamlit==1.60.0
sudo install -m 0600 /tmp/yanhai-labs-deploy/evidence.env.example /etc/yanhai-evidence-lab.env
sudoedit /etc/yanhai-evidence-lab.env
sudo install -m 0644 /tmp/yanhai-labs-deploy/yanhai-evidence-lab.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yanhai-evidence-lab
curl --fail http://127.0.0.1:8501/AgentDemo/lab/
```

把示例密码替换为长随机值，不能保留或提交示例值。

## 4. 购买与初始化 GN7

账号负责人在腾讯云中国区购买页选择按量计费 GN7：1×T4 16 GiB、8 vCPU、32 GiB、
100 GB SSD、Ubuntu 22.04，优先与 `snowsong.top` 同地域。安全组只允许项目管理来源访问
SSH，不开放 8502 或 18502。

环境契约为 `/tmp/yanhai-labs-deploy/tencent-gn7-env.json`。首次连接先安装并核对契约中的
系统包：

```bash
sudo apt-get update
sudo apt-get install --yes ca-certificates curl git openssh-client
dpkg-query -W -f='${binary:Package}\t${Status}\n' ca-certificates curl git openssh-client
```

### GPU 空闲闸门

环境安装、模型下载、模型加载和服务启动前都要重跑以下预检。名称必须包含 `T4`，Linux 驱动
不得低于 570.26，且 `memory.used` 必须小于 500 MiB；否则立即停止，不抢占其他任务：

```bash
gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)"
driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1)"
gpu_memory_used_mib="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n 1 | tr -d ' ')"
printf 'GPU=%s DRIVER=%s MEMORY_USED_MIB=%s\n' "$gpu_name" "$driver_version" "$gpu_memory_used_mib"
case "$gpu_name" in *T4*) ;; *) echo "目标不是 NVIDIA T4" >&2; exit 1;; esac
dpkg --compare-versions "$driver_version" ge 570.26 || { echo "NVIDIA 驱动低于 570.26" >&2; exit 1; }
test "$gpu_memory_used_mib" -lt 500 || { echo "GPU 非空闲：memory.used 必须低于 500 MiB" >&2; exit 1; }
```

预检通过后安装单文件和固定环境：

```bash
id yanhai-gliner >/dev/null 2>&1 || sudo useradd --system --home /var/lib/yanhai-gliner --shell /usr/sbin/nologin yanhai-gliner
sudo install -d -o root -g root /opt/yanhai-gliner/releases/0.1.0
sudo install -m 0644 /tmp/yanhai-labs-deploy/gliner_entity_lab.py /opt/yanhai-gliner/releases/0.1.0/
sudo ln -sfn /opt/yanhai-gliner/releases/0.1.0 /opt/yanhai-gliner/current
curl -fLo /tmp/Miniforge3-26.3.2-2-Linux-x86_64.sh https://github.com/conda-forge/miniforge/releases/download/26.3.2-2/Miniforge3-26.3.2-2-Linux-x86_64.sh
echo "42260ffe3830fb953d5eee1bbb32229ff06aa7c3833c1ed7a9a0420a95685d94  /tmp/Miniforge3-26.3.2-2-Linux-x86_64.sh" | sha256sum -c -
sudo bash /tmp/Miniforge3-26.3.2-2-Linux-x86_64.sh -b -p /opt/miniforge3
sudo /opt/miniforge3/bin/conda create --yes --prefix /opt/yanhai-gliner/venv python=3.12.13 pip=25.1.1
sudo /opt/yanhai-gliner/venv/bin/python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
sudo /opt/yanhai-gliner/venv/bin/python -m pip install transformers==4.57.6 gliner==0.2.27 streamlit==1.60.0 huggingface-hub==0.36.2 tokenizers==0.22.2 sentencepiece==0.2.2
sudo /opt/yanhai-gliner/venv/bin/python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
```

第三阶段重新安装 PyTorch 是环境回扣，防止第二阶段解析器换成其他 CUDA 构建。记录环境：

```bash
/opt/yanhai-gliner/venv/bin/python -m pip check
/opt/yanhai-gliner/venv/bin/python -m pip freeze --all | tee /tmp/yanhai-gliner-freeze.txt
sha256sum /tmp/yanhai-gliner-freeze.txt /tmp/yanhai-labs-deploy/tencent-gn7-env.json /opt/yanhai-gliner/current/gliner_entity_lab.py
```

## 5. 三层环境见证

每个命令都显式渲染同一份环境契约，避免交互 shell 与 systemd 不一致。

Tier 1 导入契约中的全部七个包，并强制核对固定版本：

```bash
sudo -u yanhai-gliner env CUDA_VISIBLE_DEVICES=0 HF_HOME=/var/lib/yanhai-gliner/huggingface MKL_NUM_THREADS=8 OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 TOKENIZERS_PARALLELISM=false GLINER_MODEL_DIR=/var/lib/yanhai-gliner/models/gliner_small-v2.1 /opt/yanhai-gliner/venv/bin/python -c "from importlib.metadata import version; import torch,transformers,gliner,streamlit,huggingface_hub,tokenizers,sentencepiece; expected={'torch':'2.8.0+cu128','transformers':'4.57.6','gliner':'0.2.27','streamlit':'1.60.0','huggingface-hub':'0.36.2','tokenizers':'0.22.2','sentencepiece':'0.2.2'}; actual={k:version(k) for k in expected}; assert actual==expected,(actual,expected); assert torch.version.cuda=='12.8',torch.version.cuda; print('TIER1_IMPORT_OK',actual,torch.version.cuda)"
```

Tier 2 是固定随机种子的真实 CUDA 内核；设备名必须含 `T4`、矩阵为 `(8, 8)`、校验和非零：

```bash
sudo -u yanhai-gliner env CUDA_VISIBLE_DEVICES=0 HF_HOME=/var/lib/yanhai-gliner/huggingface MKL_NUM_THREADS=8 OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 TOKENIZERS_PARALLELISM=false GLINER_MODEL_DIR=/var/lib/yanhai-gliner/models/gliner_small-v2.1 /opt/yanhai-gliner/venv/bin/python -c "import torch;torch.manual_seed(0);x=torch.randn(8,8,device='cuda');y=x@x;name=torch.cuda.get_device_name(0);checksum=float(y.abs().sum());assert y.shape==(8,8);assert 'T4' in name,name;assert checksum>0,checksum;print('WITNESS',tuple(y.shape),name,checksum)"
```

重跑 GPU 空闲闸门后，预取唯一模型到普通目录（不依赖符号链接），再加载并记录大小：

```bash
sudo install -d -o yanhai-gliner -g yanhai-gliner /var/lib/yanhai-gliner/models/gliner_small-v2.1 /var/lib/yanhai-gliner/huggingface
sudo -u yanhai-gliner env CUDA_VISIBLE_DEVICES=0 HF_HOME=/var/lib/yanhai-gliner/huggingface MKL_NUM_THREADS=8 OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 TOKENIZERS_PARALLELISM=false GLINER_MODEL_DIR=/var/lib/yanhai-gliner/models/gliner_small-v2.1 /opt/yanhai-gliner/venv/bin/python -c "from huggingface_hub import snapshot_download;snapshot_download(repo_id='urchade/gliner_small-v2.1',local_dir='/var/lib/yanhai-gliner/models/gliner_small-v2.1');print('MODEL_DOWNLOAD_OK')"
sudo -u yanhai-gliner env PYTHONPATH=/opt/yanhai-gliner/current CUDA_VISIBLE_DEVICES=0 HF_HOME=/var/lib/yanhai-gliner/huggingface MKL_NUM_THREADS=8 OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 TOKENIZERS_PARALLELISM=false GLINER_MODEL_DIR=/var/lib/yanhai-gliner/models/gliner_small-v2.1 /opt/yanhai-gliner/venv/bin/python -c "import gliner_entity_lab as lab;lab.load_model_bundle();print('MODEL_LOAD_OK')"
du -sh /var/lib/yanhai-gliner/models/gliner_small-v2.1
```

Tier 3 必须由未参与构建的人，只按本文件和环境台账，在干净会话中复现 Tier 1、Tier 2、
模型加载和服务启动。三层都通过后才可把台账从 `pending` 改为 `ready`。

## 6. 安装 GLiNER 单文件服务

重跑 GPU 空闲闸门后执行：

```bash
sudo install -m 0600 -o yanhai-gliner -g yanhai-gliner /tmp/yanhai-labs-deploy/gliner.env.example /etc/yanhai-gliner-lab.env
sudoedit /etc/yanhai-gliner-lab.env
sudo install -m 0644 /tmp/yanhai-labs-deploy/yanhai-gliner-lab.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yanhai-gliner-lab
curl --fail http://127.0.0.1:8502/AgentDemo/lab/gliner/
```

替换示例密码。服务拒绝 CPU 回退；CUDA 离线、非法输入、超时、队列已满、OOM 和 14 GiB
安全线超限都会显示明确错误。

## 7. 建立 GPU 主动反向隧道

在 GPU 节点生成专用密钥，私钥永久留在 GPU 节点：

```bash
sudo install -d -m 0700 -o yanhai-gliner -g yanhai-gliner /etc/yanhai-gliner-tunnel
sudo -u yanhai-gliner ssh-keygen -t ed25519 -N "" -f /etc/yanhai-gliner-tunnel/id_ed25519
```

所有者在公网机创建只用于反向转发的 `yanhai-tunnel` 用户，并在其 `authorized_keys` 公钥前加：

```text
restrict,port-forwarding,permitlisten="127.0.0.1:18502"
```

公网机 SSH 保持 `GatewayPorts no`。管理员通过独立可信通道核对 SSH 主机指纹，把正确主机键
写入 `/etc/yanhai-gliner-tunnel/known_hosts`，禁止 `StrictHostKeyChecking=no`。

```bash
sudo install -m 0600 -o yanhai-gliner -g yanhai-gliner /tmp/yanhai-labs-deploy/tunnel.env.example /etc/yanhai-gliner-tunnel.env
sudo install -m 0644 /tmp/yanhai-labs-deploy/yanhai-gliner-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yanhai-gliner-tunnel
sudo systemctl status yanhai-gliner-tunnel --no-pager
```

隧道只建立 `snowsong.top:127.0.0.1:18502 → GPU:127.0.0.1:8502`。

## 8. 接入 HTTPS 入口

以下操作同样必须由 `snowsong.top` 所有者授权：

```bash
sudo install -m 0644 /tmp/yanhai-labs-deploy/agentdemo-labs.locations.conf /etc/nginx/snippets/agentdemo-labs.locations.conf
sudo cp -a /etc/nginx/sites-available/mysite /etc/nginx/sites-available/mysite.before-labs
```

只在启用 HTTPS 的 `server {}` 中加入：

```nginx
include /etc/nginx/snippets/agentdemo-labs.locations.conf;
```

然后原子检查并热加载：

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail --head https://snowsong.top/AgentDemo/lab/
curl --fail --head https://snowsong.top/AgentDemo/lab/gliner/
```

GPU 关闭时第二个地址必须明确返回 503，不能伪造“成功”。

## 9. 团队验收

1. 成员提供 3–5 条正常、边界及异常样本，全部通过脚本内强制断言；
2. 三个浏览器会话依次提交，日志中 `started_at`/`finished_at` 不重叠，`job_id`、参数和结果不串单；
3. 逐项核对 GPU 离线、非法 JSON、超时、队列满、OOM 与安全线错误；
4. 下载 JSON 结果，核对冷启动、逐案推理、总时长、峰值显存和指标；
5. 峰值 CUDA reserved 必须不超过 14336 MiB，并且只加载这一组模型。

审计目录只保存哈希、运行信息、参数、指标和案例 ID，不保存成员原文或预测实体。

## 10. 启停、费用与 CAM 边界

GPU 使用控制在 20 小时/周，并设置约 80 小时/月费用预警。停止时必须在控制台选择“关机不收费”，
或调用 `StopInstances` 并显式传入 `StoppedMode=STOP_CHARGING`，再查询实例状态确认。操作系统
内的 `shutdown` 不等于停止计费，且是否支持该模式以控制台为准。

`StartInstances` 是操作级授权，不能简单用某一个实例 QCS 达到完全的单实例资源限制。首期使用
项目隔离账号和受限操作员，保留控制台审计；不把长期 SecretId/SecretKey 存到 `snowsong.top`。

## 11. 回滚

```bash
sudo systemctl disable --now yanhai-evidence-lab
sudo systemctl disable --now yanhai-gliner-tunnel yanhai-gliner-lab
sudo cp -a /etc/nginx/sites-available/mysite.before-labs /etc/nginx/sites-available/mysite
sudo nginx -t
sudo systemctl reload nginx
```

版本回归时不删除缓存或日志，只把 `current` 软链接切回上一版本并重启对应服务。

## 官方依据

- [PyTorch 固定版本与 CUDA 12.8 安装矩阵](https://pytorch.org/get-started/previous-versions/)
- [CUDA 12.8 驱动要求](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)
- [GLiNER 0.2.27 包元数据](https://pypi.org/project/gliner/)
- [腾讯云 GPU 实例规格](https://cloud.tencent.com/document/product/560/19700)
- [腾讯云按量计费说明](https://cloud.tencent.com/document/product/560/8025)
- [腾讯云 StopInstances 与 STOP_CHARGING](https://cloud.tencent.com/document/product/213/15743)
- [腾讯云 CVM 可授权资源类型](https://intl.cloud.tencent.com/zh/document/product/598/57095)
