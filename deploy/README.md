# snowsong.top/AgentDemo 部署方案

## 已核验的现状

核验日期：2026-07-27。

- 本机：WSL 2.7.3，Ubuntu 24.04，WSL2，项目可从
  `/mnt/d/project/IndependentProjects/Multi-Agent-Scholarly-Trace-demo` 访问；
- 腾讯云：Debian 13、2 vCPU、1.9 GiB 内存、49 GB 系统盘；
- Nginx、HTTPS 和 Certbot 自动续期均已运行；
- 现有站点配置是 `/etc/nginx/sites-available/mysite`，站点根目录是
  `/var/www/mysite`；
- `https://snowsong.top/`、`/AgentDemo/`、`/AgentDemo/start/` 和
  `/AgentDemo/install/` 均返回 200；
- 云服务器当前约使用 419 MiB 内存和 2.6 GB 磁盘。

当前线上应用版本为 `/opt/yanhai-agent-demo/releases/0.2.1-c32c748`，
上一版本 `/opt/yanhai-agent-demo/releases/0.2.0-9ad5926-r2` 保留用于回滚。
SQLite 数据位于 `/var/lib/yanhai-agent-demo/yanhai.sqlite3`，不随代码版本切换。

## 目标结构

| 公网路径 | 实现 | 服务器位置 |
| --- | --- | --- |
| `/AgentDemo/` | 项目简介与入口 | `/var/www/mysite/AgentDemo/index.html` |
| `/AgentDemo/start/` | Nginx HTTPS 反代 | `127.0.0.1:8765` |
| `/AgentDemo/start/api/` | 反代、限流、请求体限制 | `127.0.0.1:8765/api/` |
| `/AgentDemo/install/` | Nginx 静态文件 | `/var/www/mysite/AgentDemo/install/` |
| `/AgentDemo` | 308 跳转 | `/AgentDemo/` |

Web 服务直接运行在腾讯云，不经过宿舍 M920q 和 FRP。这样不受宿舍网络
23:30–07:00 断网影响，也减少一层故障点。当前程序运行时没有第三方 Python
依赖，1.9 GiB 云主机足以承载验证流量。

## 本地构建

在 Windows PowerShell 中：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_qt_release.ps1 -Version 0.2.1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_web_release.ps1 -Version 0.2.1
```

产物：

- `release/YanhaiTrace-Windows-x64-0.2.1.zip`
- `release/yanhai-web-0.2.1.tar.gz`

当前验证构建校验：

```text
Qt ZIP:  e0abb3f68bc38f0aa40029424a6db6a80b438ee8f08ecd33c949c105d96b659a
Web TGZ: 5b28f7a7d0c4c102f04d92795e4402c1a6fb45cb7ea0de46afb6476b140f1048
```

Qt 构建会先运行单元测试。发布前还应使用下面的环境变量执行冻结版冒烟：

```powershell
$env:YANHAI_QT_SMOKE_TEST="1"
$env:QT_QPA_PLATFORM="offscreen"
Start-Process release/qt-dist/YanhaiTrace/YanhaiTrace.exe -Wait
```

## 日常增量更新

已有站点优先使用 `scripts/update_agentdemo_remote.sh`。它会校验 Web/Qt 哈希，
创建新版本目录，备份当前 service、环境文件和下载页，切换 `current` 后等待健康
端点就绪；若约 15 秒内仍未就绪，则恢复旧软链接和服务配置。服务器 Key 只通过
权限为 `0700` 的暂存目录传入，安装为 `root:yanhai-agent 0640` 后删除暂存副本。

发布完成后保留上一版本目录和 `/var/backups/yanhai-agent-demo/<时间>/`，不要在
用户尚未验收时清理。

## 首次上线步骤

以下步骤会修改服务器，应在维护窗口内执行。

### 1. 上传到服务器暂存区

从 WSL 执行：

```bash
cd /mnt/d/project/IndependentProjects/Multi-Agent-Scholarly-Trace-demo
scp release/yanhai-web-0.2.1.tar.gz TencentCloud:/tmp/
scp release/YanhaiTrace-Windows-x64-0.2.1.zip TencentCloud:/tmp/
scp -r deploy TencentCloud:/tmp/yanhai-deploy
```

### 2. 安装一个可回滚的应用版本

服务器执行：

```bash
id yanhai-agent >/dev/null 2>&1 ||
  useradd --system --home /nonexistent --shell /usr/sbin/nologin yanhai-agent

install -d -o root -g root /opt/yanhai-agent-demo/releases/<release-id>
tar -xzf /tmp/yanhai-web-0.2.1.tar.gz \
  -C /opt/yanhai-agent-demo/releases/<release-id>
chown -R root:root /opt/yanhai-agent-demo/releases/<release-id>
ln -sfn /opt/yanhai-agent-demo/releases/<release-id> /opt/yanhai-agent-demo/current

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
install -m 0644 /tmp/YanhaiTrace-Windows-x64-0.2.1.zip \
  /var/www/mysite/AgentDemo/install/YanhaiTrace-Windows-x64-0.2.1.zip
```

上传前后的 SHA-256 必须相同：

```text
e0abb3f68bc38f0aa40029424a6db6a80b438ee8f08ecd33c949c105d96b659a
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
curl --fail --output /dev/null https://snowsong.top/AgentDemo/start/
curl --fail --head https://snowsong.top/AgentDemo/install/
curl --fail --head \
  https://snowsong.top/AgentDemo/install/YanhaiTrace-Windows-x64-0.2.1.zip
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
- 当前公开验证版提供账号、版本化画像和服务器托管的免费 DeepSeek；
- 公开注册通过 `YANHAI_REGISTRATION_OPEN=1` 开启，公网 Cookie 使用
  `Secure` 且 Path 为 `/AgentDemo/start/`；
- SQLite 位于 `/var/lib/yanhai-agent-demo`，服务器 Key 仅由
  `root:yanhai-agent` 以 `0640` 读取；
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
