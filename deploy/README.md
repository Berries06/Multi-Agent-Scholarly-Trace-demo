# snowsong.top/AgentDemo 部署方案

## 已核验的现状

核验日期：2026-07-26。

- 本机：WSL 2.7.3，Ubuntu 24.04，WSL2，项目可从
  `/mnt/d/project/IndependentProjects/Multi-Agent-Scholarly-Trace-demo` 访问；
- 腾讯云：Debian 13、2 vCPU、1.9 GiB 内存、49 GB 系统盘；
- Nginx、HTTPS 和 Certbot 自动续期均已运行；
- 现有站点配置是 `/etc/nginx/sites-available/mysite`，站点根目录是
  `/var/www/mysite`；
- `https://snowsong.top/` 返回 200，两个 AgentDemo 目标路径上线前均为 404；
- 云服务器当前约使用 419 MiB 内存和 2.6 GB 磁盘。

## 目标结构

| 公网路径 | 实现 | 服务器位置 |
| --- | --- | --- |
| `/AgentDemo/` | 项目简介与入口 | `/var/www/mysite/AgentDemo/index.html` |
| `/AgentDemo/start/` | Nginx HTTPS 反代 | `127.0.0.1:8765` |
| `/AgentDemo/start/api/` | 反代、限流、请求体限制 | `127.0.0.1:8765/api/` |
| `/AgentDemo/install/` | Nginx 静态文件 | `/var/www/mysite/AgentDemo/install/` |
| `/AgentDemo/lab/` | CPU 证据裁决实验台 | `127.0.0.1:8501` |
| `/AgentDemo/lab/gliner/` | GPU GLiNER 实验台（反向隧道） | `127.0.0.1:18502` |
| `/AgentDemo` | 308 跳转 | `/AgentDemo/` |

Web 服务直接运行在腾讯云，不经过宿舍 M920q 和 FRP。这样不受宿舍网络
23:30–07:00 断网影响，也减少一层故障点。当前程序运行时没有第三方 Python
依赖，1.9 GiB 云主机足以承载验证流量。

共享实验台的授权闸门、固定环境、反向隧道、费用记录、验收和回滚步骤见
[`labs/README.md`](labs/README.md)。该手册未授权任何人直接修改成员个人服务器
或购买 GPU。

## 本地构建

在 Windows PowerShell 中：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_qt_release.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_web_release.ps1
```

产物：

- `release/YanhaiTrace-Windows-x64-0.1.0.zip`
- `release/yanhai-web-0.1.0.tar.gz`

当前验证构建校验：

```text
Qt ZIP:  ac0f4b453c83afba531f4e84aaaf00b4cddd6a0b20f4ea85b449cafb51c99d6d
Web TGZ: 4c18af75c88d40fd898abc9494667069f5c963dc00c1c5cc1489e298017ebbbd
```

Qt 构建会先运行单元测试。发布前还应使用下面的环境变量执行冻结版冒烟：

```powershell
$env:YANHAI_QT_SMOKE_TEST="1"
$env:QT_QPA_PLATFORM="offscreen"
Start-Process release/qt-dist/YanhaiTrace/YanhaiTrace.exe -Wait
```

## 首次上线步骤

以下步骤会修改服务器，应在维护窗口内执行。

### 1. 上传到服务器暂存区

从 WSL 执行：

```bash
cd /mnt/d/project/IndependentProjects/Multi-Agent-Scholarly-Trace-demo
scp release/yanhai-web-0.1.0.tar.gz TencentCloud:/tmp/
scp release/YanhaiTrace-Windows-x64-0.1.0.zip TencentCloud:/tmp/
scp -r deploy TencentCloud:/tmp/yanhai-deploy
```

### 2. 安装一个可回滚的应用版本

服务器执行：

```bash
id yanhai-agent >/dev/null 2>&1 ||
  useradd --system --home /nonexistent --shell /usr/sbin/nologin yanhai-agent

install -d -o root -g root /opt/yanhai-agent-demo/releases/0.1.0
tar -xzf /tmp/yanhai-web-0.1.0.tar.gz \
  -C /opt/yanhai-agent-demo/releases/0.1.0
chown -R root:root /opt/yanhai-agent-demo/releases/0.1.0
ln -sfn /opt/yanhai-agent-demo/releases/0.1.0 /opt/yanhai-agent-demo/current

install -m 0644 /tmp/yanhai-deploy/systemd/yanhai-agent-demo.service \
  /etc/systemd/system/yanhai-agent-demo.service
systemctl daemon-reload
systemctl enable --now yanhai-agent-demo
curl --fail --silent http://127.0.0.1:8765/api/health
```

### 3. 安装主站入口、AgentDemo 页面、下载页与 Qt 包

服务器执行：

```bash
install -m 0644 /tmp/yanhai-deploy/main-site/index.html \
  /var/www/mysite/index.html
install -d -m 0755 /var/www/mysite/AgentDemo
install -m 0644 /tmp/yanhai-deploy/landing/index.html \
  /var/www/mysite/AgentDemo/index.html
install -d -m 0755 /var/www/mysite/AgentDemo/install
install -m 0644 /tmp/yanhai-deploy/install/index.html \
  /var/www/mysite/AgentDemo/install/index.html
install -m 0644 /tmp/yanhai-deploy/install/styles.css \
  /var/www/mysite/AgentDemo/install/styles.css
install -m 0644 /tmp/YanhaiTrace-Windows-x64-0.1.0.zip \
  /var/www/mysite/AgentDemo/install/YanhaiTrace-Windows-x64-0.1.0.zip
```

上传前后的 SHA-256 必须相同：

```text
ac0f4b453c83afba531f4e84aaaf00b4cddd6a0b20f4ea85b449cafb51c99d6d
```

### 4. 增量接入 Nginx

服务器执行：

```bash
install -m 0644 /tmp/yanhai-deploy/nginx/agentdemo-rate-limit.conf \
  /etc/nginx/conf.d/agentdemo-rate-limit.conf
install -m 0644 /tmp/yanhai-deploy/nginx/agentdemo.locations.conf \
  /etc/nginx/snippets/agentdemo.locations.conf
cp -a /etc/nginx/sites-available/mysite \
  /etc/nginx/sites-available/mysite.before-agentdemo
```

然后只在 `mysite` 的第一个、启用 HTTPS 的 `server { ... }` 内加入一行：

```nginx
include /etc/nginx/snippets/agentdemo.locations.conf;
```

不要把它加入 Certbot 管理的 HTTP 跳转 `server`。检查并热加载：

```bash
nginx -t
systemctl reload nginx
```

## 上线验收

```bash
curl --fail https://snowsong.top/AgentDemo/start/api/health
curl --fail --head https://snowsong.top/
curl --fail --head https://snowsong.top/AgentDemo/
curl --fail --head https://snowsong.top/AgentDemo/start/
curl --fail --head https://snowsong.top/AgentDemo/install/
curl --fail --head \
  https://snowsong.top/AgentDemo/install/YanhaiTrace-Windows-x64-0.1.0.zip
journalctl -u yanhai-agent-demo --since "10 minutes ago" --no-pager
```

浏览器再验证：

1. 个人主页的导航和 Hero 按钮都能进入 AgentDemo；
2. AgentDemo 介绍页的直接使用、下载和 GitHub 链接正确；
3. Mock 能完整运行；
4. 四个供应商可以选择，模型 ID 可以修改；
5. 使用一个低额度测试 Key 执行“测试连接”；
6. 页面刷新后 API Key 不存在；
7. `/AgentDemo/install/` 可以下载 ZIP，并能通过 SHA-256 校验。

## 密钥与运行边界

- API Key 仅随本次 HTTPS JSON 请求进入 Python 进程内存；
- 前端不使用 Cookie、`localStorage` 或 `sessionStorage` 保存 Key；
- 后端日志只记录方法、路径和状态，不记录请求体；
- Nginx 默认 access log 不记录请求体，API 位置额外返回 `no-store`；
- 每个公网 IP 的 API 基础速率为 30 次/分钟，突发 10 次；
- 当前是公开验证版，不提供账户系统或服务端代管 Key；
- 供应商调用和 arXiv 检索会从腾讯云公网发起，正式开放前应确认各供应商
  对服务器区域、数据处理和用户自带 Key 的条款。

Web 版或 Qt 版更新后，合作者必须联系宋明浩
`06245011@cumt.edu.cn` 更新网站。`snowsong.top` 使用宋明浩个人主页的
域名与服务器，GitHub 提交不会自动发布。

## 回滚

若 Web 服务异常：

```bash
systemctl disable --now yanhai-agent-demo
```

若 Nginx 接入异常，恢复备份并检查后热加载：

```bash
cp -a /etc/nginx/sites-available/mysite.before-agentdemo \
  /etc/nginx/sites-available/mysite
nginx -t && systemctl reload nginx
```

如果只是新版本回归，保留 systemd 与 Nginx，不动现网配置，直接把
`/opt/yanhai-agent-demo/current` 软链接切回上一个 release，再重启服务即可。
