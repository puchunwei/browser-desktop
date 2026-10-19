# Changelog

## <TAG>

- 首个公开镜像：Google Chrome 155.0.8059.84，xrdp 0.10.6.1（Unicode 输入、光标、旋转补丁）。
- 运行时配置桌面账号；首次启动生成 RDP 密码与 TLS 证书；缺少必需运行参数时拒绝启动。
- 附带 Chrome seccomp 配置；不可用时以 `--no-sandbox` 运行并警告。
