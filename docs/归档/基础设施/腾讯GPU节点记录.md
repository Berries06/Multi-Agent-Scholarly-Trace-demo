# 腾讯云 GN7 环境台账

### env: tencent-gn7@58085959

- spec: `deploy/labs/tencent-gn7-env.json`
- canonical_sha256: `58085959ee293c5ff99421eda830b4d84ad4f271c0e84319825821bdfe0177f7`
- raw_file_sha256: `fb519e5019143d10bc0ec7cf0d5cd33987a7dd8c2c306a4fe687bd20a2ca083e`
- canonicalization: 解析 JSON，然后以 `sort_keys=True,separators=(',',':')` 无空白序列化并计算 SHA-256；环境键使用前 8 位。
- how: `pending`；账号负责人尚未授权或购买腾讯云中国区按量 GN7，目标为 Ubuntu 22.04 直接 SSH 主机上的 `/opt/yanhai-gliner/venv`。
- tier: `{cpus: 8, mem_gib: 32, gpus: 1, gpu: NVIDIA T4 16 GiB, disk_gib: 100}`
- weights: `pending`；计划为 `GLINER_MODEL_DIR=/var/lib/yanhai-gliner/models/gliner_small-v2.1`，由 `snapshot_download` 和真实加载器验证。
- tier_1_imports: `pending`
- tier_2_seeded_cuda_witness: `pending`
- tier_3_agent_follows_doc: `pending`
- validated: `pending`；只有 GN7 上三层见证和成员语义样本全部通过后才能改为日期。
- gotcha: 每次环境安装、模型下载、模型加载和服务启动前，`nvidia-smi memory.used` 必须小于 500 MiB。

## 固定目标

- 实例：GN7，1×NVIDIA T4 16 GiB，8 vCPU，32 GiB，100 GB SSD
- 系统：Ubuntu 22.04 x86-64
- 驱动：Linux NVIDIA driver >= 570.26
- Python：CPython 3.12.13；pip 25.1.1
- PyTorch：2.8.0+cu128
- 直接依赖：transformers 4.57.6、gliner 0.2.27、streamlit 1.60.0
- 兼容固定：huggingface-hub 0.36.2、tokenizers 0.22.2、sentencepiece 0.2.2
- 模型：`urchade/gliner_small-v2.1`
- 购买页价格记录：`pending`
- 成员提供的 3–5 条语义样本：`pending`
- `gliner_entity_lab.py` SHA-256：`f63cbce7d69b389f339264ac2205c56d22bbb49446e67ecdcbfe21f80b0816ea`
- `shared_evidence_decision_lab.py` SHA-256：`e7313f7222df5546e88f095a21d630787049a066d511726331bd275ca4875f17`

## 本机先行见证（不等价于 T4 ready）

- 时间：2026-08-16（Asia/Shanghai）
- 系统：Windows 11 x86-64；CPython 3.12.13
- GPU：NVIDIA GeForce RTX 5070 Laptop GPU；驱动 592.27
- 正式预检：`FAIL`；观测到 `memory.used=1452 MiB`，高于 500 MiB 空闲闸门，因此本机环境不得标记为 validated。
- 导入：torch 2.8.0+cu128 / CUDA 12.8 / transformers 4.57.6 / gliner 0.2.27 / streamlit 1.60.0；`pip check` 无冲突。
- 先行 CUDA 见证：`WITNESS (8, 8) ... 114.36102294921875 8.13`。此短见证发生在正式空闲闸门补入文档前，只证明本机内核可调度，不能替代 T4/Linux Tier 2。
- 先行 GLiNER 冷加载：27.6263 秒；峰值 CUDA allocated 584.3 MiB、reserved 620.0 MiB。不能计作 GN7 模型见证。
- GLiNER 模型目录：621782611 bytes
- Windows ASCII tokenizer 缓存：4930199 bytes
- 本机完整锁：`deploy/labs/windows-cpython312-lock.txt`；SHA-256 `427fb90c0b1ea7bd338b1370c371b13b276a3e2801b2a4179059c22b5f6062fe`
- 成员语义验收：`pending`；没有用 AI 自拟案例替代。

GN7 验证完成时追加脱敏实例 ID、地域、驱动版本、`pip freeze` 哈希、模型缓存大小、三层见证原始输出路径和验证人；不得写入云密钥、共享密码或成员原文。
