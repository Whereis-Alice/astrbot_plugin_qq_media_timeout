# QQ 视频发送等待保护

为 AstrBot 的 OneBot 反向 WebSocket 视频发送单独设置较长的等待上限，避免视频仍在上传时就出现 `WebSocket API call timeout`。默认上限为 1800 秒（30 分钟），上传完成便立即返回。

## 安装与更新

在 AstrBot 插件管理中选择“从链接安装”，输入：

```text
https://github.com/Whereis-Alice/astrbot_plugin_qq_media_timeout
```

已手动安装的同名插件应保留目录名 `astrbot_plugin_qq_media_timeout`，并补齐本仓库的 `metadata.yaml`；其中的 `repo` 字段用于指向更新仓库。若当前 AstrBot 记录的安装来源为“本地文件”，还需在插件管理中将更新来源绑定为本仓库；仅补 `repo` 不一定会启用更新按钮。之后可通过插件管理更新。配置由 AstrBot 保存在插件目录之外，不需要在更新时复制旧源码。

兼容 AstrBot 4.16 至 4.x 的 `aiocqhttp` 平台及其 OneBot 反向 WebSocket 传输。使用 Python 标准库和 AstrBot 已有依赖，无需单独安装第三方包。

## 配置

在插件配置中调整后重新加载插件：

| 参数 | 默认值 | 范围 | 含义 |
| --- | --- | --- | --- |
| `video_timeout_sec` | `1800` | `180`–`3600` 秒 | 含视频发送请求等待结果的上限 |

非数字配置恢复为默认值；越界数字限制在上述范围内。已有比配置更长的等待上限会保留。普通请求沿用适配器原来的上限。

覆盖 `send_msg`、`send_group_msg`、`send_private_msg`、群聊/私聊合并转发和 `upload_forward_msg`，包括嵌套转发节点中的视频与未转义的 CQ 视频码。纯文本组件中作为示例出现的 CQ 码不会触发。

## 作用与限制

插件在运行时包装 `WebSocketReverseApi.call_action`，为视频请求复制 API 实例状态，只调整本次请求的超时。复制直接保留实例类型及属性，不调用 `copy.copy()` 或 pickle 协议；aiocqhttp 的动态 action 查找会把复制协议方法误当作接口，导致 `WebSocketReverseApi.call_action() takes 2 positional arguments but 3 were given`，v0.1.2 已修复。连接表仍共享，普通并发请求不受影响；不改 AstrBot 核心文件或 aiocqhttp 安装文件。

此插件只解决等待时间过短。QQ 接入端上传失败、签名失效、图片或视频资源不可下载，需要由接入端或相应媒体插件处理。延长等待不会延长 QQ 资源的保留期限，也不验证资源是否可读。

插件不重新发送聊天消息。请求超时不代表远端上传已取消，切勿只因超时自动重发，以免产生重复消息。

停用或卸载后恢复原传输方法；若其他插件之后也包装了同一方法，会保留其包装链并让本插件停用。升级 AstrBot 或 aiocqhttp 后应复核兼容性，因为本插件使用了 `_timeout_sec` 私有属性。

## 开发检查

无需安装 AstrBot；安装实际传输 SDK 后运行测试：

```bash
python -m pip install aiocqhttp==1.4.4
python -m unittest discover -s tests -v
python -m compileall -q main.py tests
```

测试覆盖视频识别、嵌套转发、并发隔离、参数透传、异常透传、超时配置及热重载/卸载，并使用真实 aiocqhttp 传输与模拟 WebSocket 回执检查视频等待。测试不连接 QQ，也不发送真实消息。

## 许可

[MIT](LICENSE)
