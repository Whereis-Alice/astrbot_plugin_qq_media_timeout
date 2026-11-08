"""Use the real reverse-WebSocket SDK without sending anything to QQ."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from aiocqhttp.api_impl import ResultStore, WebSocketReverseApi
from aiocqhttp.exceptions import NetworkError


PLUGIN = Path(__file__).resolve().parents[1] / "main.py"
VIDEO = [{"type": "video", "data": {"file": "file:///video.mp4"}}]


class RealAiocqhttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class Star:
            def __init__(self, context):
                self.context = context

        modules = {
            "astrbot": types.ModuleType("astrbot"),
            "astrbot.api": types.ModuleType("astrbot.api"),
            "astrbot.api.star": types.ModuleType("astrbot.api.star"),
        }
        modules["astrbot.api"].AstrBotConfig = dict
        modules["astrbot.api"].logger = types.SimpleNamespace(info=lambda *a, **k: None)
        modules["astrbot.api.star"].Context = object
        modules["astrbot.api.star"].Star = Star
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("real_timeout_plugin_under_test", PLUGIN)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.Plugin = module.QQMediaTimeoutPlugin
        self.native_call_action = WebSocketReverseApi.call_action
        self.observed = []
        self.receipt_timers = []

        async def observe(api, action, **params):
            self.observed.append((api, action, params))
            return await self.native_call_action(api, action, **params)

        self.observer = observe
        WebSocketReverseApi.call_action = observe
        self.plugin = self.Plugin(object())
        self.plugin.video_timeout_sec = 0.5
        self.plugins = [self.plugin]
        await self.plugin.initialize()

    async def asyncTearDown(self):
        try:
            for plugin in reversed(self.plugins):
                await plugin.terminate()
        finally:
            WebSocketReverseApi.call_action = self.native_call_action
            for timer in self.receipt_timers:
                timer.cancel()

    def respond_after(self, request, delay):
        self.receipt_timers.append(asyncio.get_running_loop().call_later(
            delay, ResultStore.add,
            {"echo": request["echo"], "status": "ok", "retcode": 0,
             "data": {"message_id": "sent"}},
        ))

    async def test_video_receipt_outlives_shared_timeout_while_ordinary_call_expires(self):
        requests = []
        video_sent = asyncio.Event()

        async def send(raw):
            request = json.loads(raw)
            requests.append(request)
            if request["action"] == "send_group_msg":
                self.respond_after(request, 0.04)
                video_sent.set()

        api = WebSocketReverseApi({"123": types.SimpleNamespace(send=send)}, set(), 0.005)
        api.custom_state = object()
        initial_state = dict(vars(api))
        sending = asyncio.create_task(api.call_action(
            "send_group_msg", self_id="123", group_id=456, message=VIDEO,
        ))
        await video_sent.wait()
        with self.assertRaises(NetworkError):
            await api.call_action("get_status", self_id="123")
        self.assertEqual(await sending, {"message_id": "sent"})
        selected, action, params = self.observed[0]
        self.assertIs(type(selected), WebSocketReverseApi)
        self.assertIsNot(selected, api)
        self.assertEqual(selected._timeout_sec, 0.5)
        for key, value in initial_state.items():
            if key != "_timeout_sec":
                self.assertIs(vars(selected)[key], value)
        self.assertEqual(vars(api), initial_state)
        self.assertIs(self.observed[1][0], api)
        self.assertEqual(self.observed[1][0]._timeout_sec, 0.005)
        self.assertEqual([request["action"] for request in requests], ["send_group_msg", "get_status"])
        self.assertEqual(params["message"], VIDEO)
        self.assertNotIn("timeout", params)
        self.assertTrue(all(request["echo"]["seq"] not in ResultStore._futures for request in requests))

    async def test_cancelled_real_video_wait_releases_receipt_without_retry(self):
        requests = []
        sent = asyncio.Event()

        async def send(raw):
            requests.append(json.loads(raw))
            sent.set()

        api = WebSocketReverseApi({"123": types.SimpleNamespace(send=send)}, set(), 0.005)
        sending = asyncio.create_task(api.call_action("send_msg", self_id="123", message=VIDEO))
        await sent.wait()
        sequence = requests[0]["echo"]["seq"]
        self.assertIn(sequence, ResultStore._futures)
        sending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await sending
        self.assertNotIn(sequence, ResultStore._futures)
        self.assertEqual(len(requests), 1)
        self.assertEqual(api._timeout_sec, 0.005)

    async def test_reload_and_unload_preserve_real_transport_and_connections(self):
        requests = []

        async def send(raw):
            request = json.loads(raw)
            requests.append(request)
            self.respond_after(request, 0)

        api = WebSocketReverseApi({"123": types.SimpleNamespace(send=send)}, set(), 0.2)
        reloaded = self.Plugin(object())
        reloaded.video_timeout_sec = 0.8
        self.plugins.append(reloaded)
        await reloaded.initialize()
        new_wrapper = WebSocketReverseApi.call_action
        self.assertIs(new_wrapper.__wrapped__, self.observer)
        await self.plugin.terminate()
        self.assertIs(WebSocketReverseApi.call_action, new_wrapper)
        self.assertEqual(await api.call_action("send_msg", self_id="123", message=VIDEO), {"message_id": "sent"})
        self.assertEqual(self.observed[-1][0]._timeout_sec, 0.8)
        self.assertIs(self.observed[-1][0]._api_clients, api._api_clients)
        await reloaded.terminate()
        self.assertIs(WebSocketReverseApi.call_action, self.observer)
        self.assertEqual(await api.call_action("send_msg", self_id="123", message=VIDEO), {"message_id": "sent"})
        self.assertIs(self.observed[-1][0], api)
        self.assertEqual(api._timeout_sec, 0.2)
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
