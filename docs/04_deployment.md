# 部署说明

## 1. 环境要求

- Windows、macOS 或 Linux；
- Python 3.11 及以上；
- 一个现代浏览器；
- 基础版不需要数据库、Node.js、模型 API 或联网环境。

## 2. 本地启动

Windows PowerShell：

```powershell
$env:PYTHONPATH="src"
python -m yanhai --host 127.0.0.1 --port 8765
```

macOS / Linux：

```bash
PYTHONPATH=src python -m yanhai --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765`。健康检查地址为：

```text
http://127.0.0.1:8765/api/health
```

## 3. 可选安装

也可以在虚拟环境中以可编辑模式安装：

```bash
python -m venv .venv
python -m pip install -e .
yanhai
```

运行时无第三方 Python 依赖；`setuptools` 仅用于可选安装。

## 4. 核心 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 服务健康状态 |
| GET | `/api/profiles` | 获取合成画像 |
| GET | `/api/knowledge-base` | 获取文献与关系切片 |
| POST | `/api/run` | 运行完整协同闭环 |
| POST | `/api/feedback` | 基于反馈重算资源 |

运行示例：

```json
{
  "profile_id": "graduate_cross_domain",
  "query": "多智能体科研推理如何降低幻觉？"
}
```

反馈示例：

```json
{
  "profile_id": "graduate_cross_domain",
  "query": "多智能体科研推理如何降低幻觉？",
  "feedback": "too_hard"
}
```

`feedback` 可取 `too_hard`、`suitable` 或 `too_easy`。

## 5. 测试

```bash
python -m unittest discover -s tests -v
python scripts/evaluate.py
```

评测结果会写入 `outputs/engineering-evaluation.json`。该文件是工程回归产物，不是正式赛事盲审结果。

## 6. 现场演示建议

- 提前启动本地服务并检查 `/api/health`；
- 不依赖公网或模型 API，避免现场网络风险；
- 准备本科生与企业分析师两条不同演示路径；
- 保留命令行输出作为浏览器异常时的后备；
- 正式版接入大模型后，仍保留当前规则基线作为离线降级路径。
