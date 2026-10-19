# Chrome seccomp 配置

基于 [Moby v26.1.3 默认配置](https://github.com/moby/moby/blob/v26.1.3/profiles/seccomp/default.json)，原文件 SHA256：

`9c1025c88ccaa517b648da571961838744ea2137f176bfe6a48b21294cae9c76`

保留全部原有规则，只在末尾增加一条允许 `clone`、`setns`、`unshare` 的规则，供普通用户 Chrome 创建沙箱命名空间。
这是 [Playwright 官方 Docker 指南](https://playwright.dev/docs/docker#crawling-and-scraping) 推荐的方式；
不使用 `seccomp=unconfined`、特权模式或 `SYS_ADMIN`。镜像内同一文件位于 `/usr/share/browser-desktop/chrome-seccomp.json`。

原配置由 Moby 项目以 Apache License 2.0 发布，见仓库根目录 `LICENSE` 与本目录 `NOTICE`。
