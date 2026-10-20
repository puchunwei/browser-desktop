# 安全说明 / Security

- **单一受信任用户。** 容器不是不受信任租户之间的隔离边界；不要把多个人放进同一个实例。
- **RDP 暴露公网时**，用防火墙或安全组限定来源 IP，或只通过 SSH 隧道、VPN、Tailscale 访问。
  默认使用 24 字节随机密码与 TLS；首次连接核对日志中的证书 SHA256 指纹，或换成自己的证书。
  自设密码至少 20 个字符。`RDP_PASSWORD` 会出现在 `docker inspect` 中，写有密码的 `compose.yaml` 不要提交到公开仓库；
  对公网开放时优先用 `RDP_PASSWORD_FILE` 指向 Docker secret。镜像不会把密码写入日志或传给浏览器进程。
- **CDP 没有认证**，等同完整的浏览器控制权。保持默认的容器回环监听；需要时只发布到宿主 `127.0.0.1`。
- **沙箱。** 使用仓库提供的 seccomp 配置让 Chrome 启用命名空间与 seccomp-BPF 沙箱；
  不要使用 `--privileged`、`seccomp=unconfined` 或 `SYS_ADMIN`。
- **数据卷** 含登录状态、Cookie、下载与 RDP 密码，备份文件同样私密。
- **更新。** 浏览器漏洞修复很快，请跟随新 tag 升级。

发现安全问题请通过 GitHub 私密漏洞报告（Security → Report a vulnerability）联系，不要公开提交 issue。
