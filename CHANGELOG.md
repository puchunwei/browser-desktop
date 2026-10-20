# Changelog

## 155.0.8059.84-20261020

- 新增 `RDP_PASSWORD`：可在 Compose 中直接设置 RDP 密码，与 `RDP_PASSWORD_FILE` 二选一。
  密码不进日志，也不传给浏览器进程。
- 部署示例合并为仓库根目录的单个 `compose.yaml`（含用户名、密码与全部必需参数），
  直接引用仓库内 `seccomp/chrome.json`；删除 `examples/compose.yml` 与 `examples/.env.example`。
- 内置拼音输入法（ibus-libpinyin）：电脑键盘客户端（如 Jump Desktop）默认英文，Shift 切换中文；
  xrdp Unicode 引擎改为收到 Unicode 字符时才接管，手机输入不变（`lazy-unicode-engine.patch`）。

## 155.0.8059.84-20261019

- 首个公开镜像：Google Chrome 155.0.8059.84，xrdp 0.10.6.1（Unicode 输入、光标、旋转补丁）。
- 运行时配置桌面账号；首次启动生成 RDP 密码与 TLS 证书；缺少必需运行参数时拒绝启动。
- 附带 Chrome seccomp 配置；不可用时以 `--no-sandbox` 运行并警告。
