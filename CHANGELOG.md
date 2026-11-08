# 更新记录

## v0.1.2 (2026-11-09)

- 修复含视频请求复制真实 aiocqhttp API 时触发动态 `__setstate__` action，导致 `WebSocketReverseApi.call_action() takes 2 positional arguments but 3 were given` 的错误。
- 请求局部状态复制跳过 copy/pickle 协议，保留实例状态与连接表，仅调整本次等待上限。
- 增加真实 aiocqhttp SDK 的视频回执、并发隔离、取消清理及重载验证，并纳入 CI。

## v0.1.1

- 补全 GitHub 更新仓库、平台及版本兼容元数据。
- 添加安装、配置、更新和卸载说明，明确媒体资源可读性不属于本插件的职责。
- 收录 16 项隔离测试及 GitHub Actions 检查。
- 保留 v0.1.0 的视频等待和普通请求隔离行为。

## v0.1.0

- 为含视频的 OneBot 反向 WebSocket 发送请求提供可配置等待上限。
- 支持嵌套转发、CQ 视频码，以及热重载和卸载恢复。
