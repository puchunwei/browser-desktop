# browser-desktop

常驻的 Google Chrome 桌面，通过 RDP 远程使用。断开连接后浏览器和标签页继续运行，
再次连接回到同一画面；屏幕分辨率跟随客户端，支持手机横竖屏切换，手机与电脑键盘都能输入中文。
同机程序可以通过 Chrome DevTools Protocol（CDP）操作同一个浏览器。

- 镜像：`ghcr.io/puchunwei/browser-desktop`，仅 linux/amd64（仅在 Linux AMD64 上验证）。
- 一个实例只给一个受信任的人使用。需要多人时，每人一个独立实例和数据卷。
- 镜像内含未修改的 Google Chrome。**使用本镜像即表示接受 [Google Chrome 服务条款](https://www.google.com/chrome/terms/)。**
- 其他第三方组件及许可见镜像内 `/usr/share/doc/browser-desktop/NOTICE`。

[English](README.en.md) · [安全说明](SECURITY.md) · [变更记录](CHANGELOG.md)

## 快速开始

一条命令，不需要先克隆仓库或手动编辑文件：

```bash
curl -fsSL https://raw.githubusercontent.com/puchunwei/browser-desktop/main/install.sh | bash
```

脚本会下载 `compose.yaml` 和它引用的 `seccomp/chrome.json`，生成一个随机密码并启动容器，
最后打印用户名、密码和端口。用 RDP 客户端（Windows App / Microsoft Remote Desktop / Jump Desktop / FreeRDP 等）
连接打印出来的端口即可。

想自己指定用户名和密码，或者装到别的目录：

```bash
DESKTOP_USER=alice RDP_PASSWORD='自己的密码，至少20个字符不含冒号' BROWSER_DESKTOP_DIR=my-browser \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/puchunwei/browser-desktop/main/install.sh)"
```

脚本只下载和运行这两个公开文件，不会收集任何信息；内容可以在执行前自己看一眼：
[`install.sh`](install.sh)。

### 克隆仓库手动安装

想先看一眼配置，或者要自己改 `compose.yaml` 的，克隆仓库后所有配置都在根目录这一个文件里：

```bash
git clone https://github.com/puchunwei/browser-desktop.git && cd browser-desktop
vi compose.yaml        # 改 DESKTOP_USER 与 RDP_PASSWORD（至少 20 个字符，不含冒号）
docker compose up -d
docker compose logs browser-desktop | grep 'RDP TLS certificate SHA256'   # 证书指纹，首次连接时核对
```

不想克隆仓库时，下载 `compose.yaml` 和它引用的 `seccomp/chrome.json` 两个文件即可：

```bash
mkdir -p browser-desktop/seccomp && cd browser-desktop
curl -fsSLO https://raw.githubusercontent.com/puchunwei/browser-desktop/main/compose.yaml
curl -fsSL https://raw.githubusercontent.com/puchunwei/browser-desktop/main/seccomp/chrome.json -o seccomp/chrome.json
```

`compose.yaml` 里标明必需的 `shm_size`、`tmpfs` 不要删除，缺少时容器拒绝启动；
`security_opt` 让 Chrome 启用自身沙箱，缺少时以 `--no-sandbox` 运行并在日志中警告；
`stop_grace_period: 30s` 让 Chrome 停止前写盘，Docker 默认 10 秒可能丢失 Cookie。

## 等价的 docker run

在仓库目录中执行（`seccomp/chrome.json` 也可以从镜像导出：
`docker run --rm --entrypoint cat ghcr.io/puchunwei/browser-desktop:latest /usr/share/browser-desktop/chrome-seccomp.json > chrome.json`）：

```bash
docker run -d --name browser-desktop \
  --shm-size 2g --stop-timeout 30 \
  --tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755 \
  --security-opt seccomp="$PWD/seccomp/chrome.json" \
  -e DESKTOP_USER=browser -e RDP_PASSWORD='至少20个字符的密码' \
  -p 3389:3389 -v browser-desktop-data:/data \
  --restart unless-stopped ghcr.io/puchunwei/browser-desktop:latest
```

## 配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DESKTOP_USER` | `browser` | RDP 登录名，也是运行 Chrome 的账号 |
| `RDP_PORT` / `RDP_BIND_ADDRESS` | `3389` / `0.0.0.0` | 容器内 RDP 监听 |
| `RDP_PASSWORD` | 空 | RDP 密码，至少 20 个字符且不含冒号；每次启动写入 `/data/rdp/password`，改值后重建容器即生效。为空时见下一行 |
| `RDP_PASSWORD_FILE` | `/data/rdp/password` | 从文件读取密码（如 Docker secret），与 `RDP_PASSWORD` 二选一；都不设时首次启动在默认位置生成随机密码 |
| `CDP_PORT` / `CDP_BIND_ADDRESS` | `9222` / `127.0.0.1` | CDP 转发，默认只在容器内可用 |
| `BROWSER_PROXY_SERVER` / `BROWSER_PROXY_BYPASS` | 空 | Chrome 启动代理与直连列表 |
| `TZ` / `LANGUAGE` | `Asia/Shanghai` / `zh_CN` | 时区与 Chrome 界面语言 |
| `SESSION_GEOMETRY` | `1366x768` | 尚无客户端时的初始桌面尺寸 |
| `CURSOR_STYLE` | `arrow` | `arrow`：链接处保持清晰箭头；`native`：恢复手形 |
| `BROWSER_PROFILE_DIR` / `BROWSER_DOWNLOADS_DIR` / `RDP_STATE_DIR` | `/data/profile` / `/data/downloads` / `/data/rdp` | 数据位置，默认都在 `/data` 卷 |

- 自己的 TLS 证书：把 `cert.pem` 与 `key.pem` 放到数据卷的 `rdp/tls/` 后重启。
- 企业或自签 CA：把 `*.crt` 挂载到 `/ca-anchors`（只读即可）。

## 让同机程序使用 CDP

CDP 没有认证，等同完整的浏览器控制权（读取 Cookie、以登录状态发请求）。只发布到宿主回环：

```yaml
    ports:
      - "3389:3389"
      - "127.0.0.1:9222:9222"
    environment:
      CDP_BIND_ADDRESS: "0.0.0.0"
```

Playwright 示例：`chromium.connectOverCDP('http://127.0.0.1:9222')`。附着已有浏览器，不要调用 `setViewportSize`，以免改动人看到的桌面。

## 数据、备份与升级

数据全部在 `/data`：`profile/`（浏览器资料）、`downloads/`、`rdp/`（密码与证书，私有）。

```bash
docker compose stop                                  # 冷备份：先停止，确保 Chrome 写盘
docker run --rm -v browser-desktop_browser-desktop-data:/data -v "$PWD":/backup \
  debian:trixie-slim tar -C /data -czf /backup/browser-desktop-$(date +%Y%m%d).tgz .
docker compose start
```

升级：备份后把 `image:` 改成新 tag，`docker compose pull && docker compose up -d`。
镜像拒绝打开由更新版本 Chrome 写过的资料，防止降级损坏；回退旧版本时需要同时恢复旧备份。

## 使用提示

- 同一账号只有一个桌面，后连接的 RDP 客户端接管会话；切换设备前先断开前一个客户端。
- iPhone 上的 Jump Desktop：先关闭 Retina，使用与手机相近的分辨率（竖屏可从 `640×1386` 开始），启用动态分辨率。
- 浏览器窗口被关闭后会自动重新打开并恢复标签页。
- 手机键盘中文通过 RDP Unicode 输入直接送达，不依赖剪贴板。
- 电脑键盘（Jump Desktop、Windows 远程桌面等发送物理按键的客户端）使用镜像内置的拼音输入法：
  默认英文，按一下 Shift 切换中文，空格或数字键选词，再按 Shift 回到英文。本机输入法对远程桌面不起作用。

## 排障

```bash
docker compose logs --tail 100 browser-desktop
```

| 日志 | 处理 |
| --- | --- |
| `/run/xrdp must be a tmpfs` | 加 `--tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755` |
| `/dev/shm must be at least 1 GiB` | 加 `--shm-size 2g` |
| `Chrome sandbox unavailable` | 保留 `compose.yaml` 的 `security_opt`，或加 `--security-opt seccomp=seccomp/chrome.json` |
| `refusing to downgrade` | 资料由更新的 Chrome 写过，换用不低于该版本的镜像 |
| `missing RDP password file` | 指定的 `RDP_PASSWORD_FILE` 不存在 |
| `RDP password must be at least 20 characters` | 加长 `RDP_PASSWORD` 或密码文件内容，且不含冒号 |
| `set either RDP_PASSWORD or RDP_PASSWORD_FILE` | 两者只能设置一个 |
| `must be writable by the desktop user` | 绑定挂载的宿主目录需允许 uid 1000 进入并写入（含各级父目录） |
