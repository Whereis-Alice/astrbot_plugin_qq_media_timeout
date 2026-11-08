from __future__ import annotations

from functools import wraps
from typing import Any

from aiocqhttp.api_impl import WebSocketReverseApi
from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star

SEND_ACTIONS = frozenset(
    {
        "send_msg",
        "send_group_msg",
        "send_private_msg",
        "send_group_forward_msg",
        "send_private_forward_msg",
        "upload_forward_msg",
    }
)


class QQMediaTimeoutPlugin(Star):
    """Keep reverse-WebSocket video sends pending while their upload completes."""

    def __init__(
        self, context: Context, config: AstrBotConfig | dict | None = None
    ) -> None:
        """Read the video wait limit and prepare wrapper ownership.

        Args:
            context: AstrBot plugin context.
            config: Optional plugin configuration.
        """
        super().__init__(context)
        try:
            configured = int((config or {}).get("video_timeout_sec", 1800))
        except (TypeError, ValueError, OverflowError):
            configured = 1800
        self.video_timeout_sec = max(180, min(3600, configured))
        self._original = None
        self._wrapper = None
        self._active = False

    async def initialize(self) -> None:
        """Install a wrapper without changing any live API object's timeout.

        Returns:
            None.
        """
        if self._wrapper is not None:
            return
        original = WebSocketReverseApi.call_action
        # Only unwrap our direct wrapper; preserve wrappers installed by others.
        previous = getattr(original, "_qq_media_timeout_original", None)
        if previous is not None and getattr(original, "__wrapped__", None) is previous:
            original = previous
        self._original = original
        self._active = True

        @wraps(original)
        async def call_action(api: Any, action: str, **params: Any) -> Any:
            """Select a request-local timeout, then run the original transport.

            Args:
                api: Reverse-WebSocket API instance.
                action: OneBot action name.
                **params: Unmodified OneBot action parameters.

            Returns:
                The original transport result.
            """
            selected = api
            if self._active and action in SEND_ACTIONS:
                pending = [params.get("message"), params.get("messages")]
                has_video = False
                while pending and not has_video:
                    value = pending.pop()
                    if isinstance(value, dict):
                        has_video = value.get("type") == "video"
                        if not has_video and value.get("type") != "text":
                            pending.extend(value.values())
                    elif isinstance(value, (list, tuple)):
                        pending.extend(value)
                    elif isinstance(value, str) and not params.get("auto_escape"):
                        has_video = "[CQ:video," in value or "[CQ:video]" in value
                if has_video and api._timeout_sec < self.video_timeout_sec:
                    # Api.__getattr__ turns copy/pickle hooks into OneBot actions.
                    # Clone its dictionary directly, keeping connection maps shared.
                    selected = object.__new__(type(api))
                    vars(selected).update(vars(api))
                    selected._timeout_sec = self.video_timeout_sec
            return await original(selected, action, **params)

        call_action._qq_media_timeout_original = original
        self._wrapper = call_action
        WebSocketReverseApi.call_action = call_action
        logger.info(
            "[QQMediaTimeout] Video request wait limit set to %s seconds; ordinary calls retain their existing timeout.",
            self.video_timeout_sec,
        )

    async def terminate(self) -> None:
        """Disable this guard and restore the transport when still owned.

        Returns:
            None.
        """
        self._active = False
        if (
            self._wrapper is not None
            and WebSocketReverseApi.call_action is self._wrapper
        ):
            WebSocketReverseApi.call_action = self._original
        self._wrapper = None
        self._original = None
