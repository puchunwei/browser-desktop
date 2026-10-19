# browser-desktop

常驻的 Google Chrome 桌面，通过 RDP 远程使用。断开连接后浏览器和标签页继续运行，
再次连接回到同一画面；屏幕分辨率跟随客户端，支持手机横竖屏切换和手机键盘中文输入。
同机程序可以通过 Chrome DevTools Protocol（CDP）操作同一个浏览器。

- 镜像：`ghcr.io/puchunwei/browser-desktop`，仅 linux/amd64（仅在 Linux AMD64 上验证）。
- 一个实例只给一个受信任的人使用。需要多人时，每人一个独立实例和数据卷。
- 镜像内含未修改的 Google Chrome。**使用本镜像即表示接受 [Google Chrome 服务条款](https://www.google.com/chrome/terms/)。**
- 其他第三方组件及许可见镜像内 `/usr/share/doc/browser-desktop/NOTICE`。

[English](README.en.md) · [安全说明](SECURITY.md) · [变更记录](CHANGELOG.md)

## 快速开始（Docker Compose）

```bash
mkdir browser-desktop && cd browser-desktop
curl -fsSLO https://raw.githubusercontent.com/puchunwei/browser-desktop/main/examples/compose.yml
docker run --rm --entrypoint cat ghcr.io/puchunwei/browser-desktop:latest \
  /usr/share/browser-desktop/chrome-seccomp.json > chrome-seccomp.json
docker compose up -d
docker compose logs browser-desktop | grep 'RDP TLS certificate SHA256'   # 证书指纹，首次连接时核对
docker exec browser-desktop cat /data/rdp/password                         # RDP 密码
```

用 RDP 客户端（Windows App / Microsoft Remote Desktop、Jump Desktop、FreeRDP 等）连接 `服务器地址:3389`，
用户名为 `DESKTOP_USER`（默认 `browser`），密码为上面读出的内容。

## 等价的 docker run

```bash
docker run -d --name browser-desktop \
  --shm-size 2g --stop-timeout 30 \
  --tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755 \
  --security-opt seccomp="$PWD/chrome-seccomp.json" \
  -p 3389:3389 -v browser-desktop-data:/data \
  --restart unless-stopped ghcr.io/puchunwei/browser-desktop:latest
```

以下三项必须保留，缺少时容器会拒绝启动或丢数据：

| 参数 | 原因 |
| --- | --- |
| `--tmpfs /run/xrdp` | 会话套接字需要 tmpfs 才能获得正确的属组，否则登录后 `Error connecting to Xorg` |
| `--shm-size 2g` | Chrome 需要足够的共享内存，小于 1 GiB 拒绝启动 |
| `--stop-timeout 30` | 停止时先让 Chrome 正常退出并写盘；Docker 默认 10 秒可能丢失 Cookie |

`--security-opt seccomp=…` 让 Chrome 启用自身沙箱。缺少时容器仍会启动，但以 `--no-sandbox` 运行并在日志中警告。

## 配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DESKTOP_USER` | `browser` | RDP 登录名，也是运行 Chrome 的账号 |
| `RDP_PORT` / `RDP_BIND_ADDRESS` | `3389` / `0.0.0.0` | 容器内 RDP 监听 |
| `RDP_PASSWORD_FILE` | `/data/rdp/password` | 默认位置缺失时首次启动自动生成；指定其他路径（如 Docker secret）时文件必须存在 |
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

## 排障

```bash
docker compose logs --tail 100 browser-desktop
```

| 日志 | 处理 |
| --- | --- |
| `/run/xrdp must be a tmpfs` | 加 `--tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755` |
| `/dev/shm must be at least 1 GiB` | 加 `--shm-size 2g` |
| `Chrome sandbox unavailable` | 加 `--security-opt seccomp=chrome-seccomp.json` |
| `refusing to downgrade` | 资料由更新的 Chrome 写过，换用不低于该版本的镜像 |
| `missing RDP password file` | 指定的 `RDP_PASSWORD_FILE` 不存在 |
| `must be writable by the desktop user` | 绑定挂载的宿主目录需允许 uid 1000 进入并写入（含各级父目录） |
