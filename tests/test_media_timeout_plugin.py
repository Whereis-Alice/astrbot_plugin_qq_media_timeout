from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from functools import wraps
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "main.py"
VIDEO = [{"type": "video", "data": {"file": "file:///video.mp4"}}]


class MediaTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class FakeApi:
            def __init__(self, timeout=180):
                self._timeout_sec = timeout
                self._api_clients = {"123456789": object()}
                self._event_clients = set()

            async def call_action(self, action, **params):
                await asyncio.sleep(0)
                return {
                    "api": self,
                    "timeout": self._timeout_sec,
                    "action": action,
                    "params": params,
                }

        class Star:
            def __init__(self, context):
                self.context = context

        modules = {
            "aiocqhttp": types.ModuleType("aiocqhttp"),
            "aiocqhttp.api_impl": types.ModuleType("aiocqhttp.api_impl"),
            "astrbot": types.ModuleType("astrbot"),
            "astrbot.api": types.ModuleType("astrbot.api"),
            "astrbot.api.star": types.ModuleType("astrbot.api.star"),
        }
        modules["aiocqhttp.api_impl"].WebSocketReverseApi = FakeApi
        modules["astrbot.api"].AstrBotConfig = dict
        modules["astrbot.api"].logger = types.SimpleNamespace(info=lambda *a, **k: None)
        modules["astrbot.api.star"].Context = object
        modules["astrbot.api.star"].Star = Star
        self.old_modules = {name: sys.modules.get(name) for name in modules}
        sys.modules.update(modules)
        spec = importlib.util.spec_from_file_location(
            "timeout_plugin_under_test", PLUGIN
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.Plugin = module.QQMediaTimeoutPlugin
        self.Api = FakeApi
        self.original = FakeApi.call_action
        self.plugin = self.Plugin(object())
        self.api = FakeApi()
        await self.plugin.initialize()

    async def asyncTearDown(self):
        await self.plugin.terminate()
        for name, original in self.old_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    async def test_ordinary_request_uses_original_object_and_timeout(self):
        result = await self.api.call_action("send_group_msg", message="hello")
        self.assertIs(result["api"], self.api)
        self.assertEqual(result["timeout"], 180)

    async def test_video_uses_local_copy_and_shared_connection_maps(self):
        result = await self.api.call_action("send_group_msg", message=VIDEO)
        self.assertEqual(result["timeout"], 1800)
        self.assertIsNot(result["api"], self.api)
        self.assertIs(result["api"]._api_clients, self.api._api_clients)
        self.assertIs(result["api"]._event_clients, self.api._event_clients)
        self.assertEqual(self.api._timeout_sec, 180)

    async def test_nested_forward_video_is_covered(self):
        nodes = [{"type": "node", "data": {"content": VIDEO}}]
        for action in (
            "send_group_forward_msg",
            "send_private_forward_msg",
            "upload_forward_msg",
        ):
            with self.subTest(action=action):
                result = await self.api.call_action(action, messages=nodes)
                self.assertEqual(result["timeout"], 1800)

    async def test_cq_video_message_string_is_covered(self):
        result = await self.api.call_action(
            "send_private_msg", message="look [CQ:video,file=a.mp4]"
        )
        self.assertEqual(result["timeout"], 1800)

    async def test_escaped_cq_string_is_not_a_video_send(self):
        result = await self.api.call_action(
            "send_msg", message="[CQ:video,file=a.mp4]", auto_escape=True
        )
        self.assertEqual(result["timeout"], 180)

    async def test_cq_literal_in_plain_text_component_is_not_video(self):
        result = await self.api.call_action(
            "send_msg",
            message=[
                {"type": "text", "data": {"text": "example [CQ:video,file=a.mp4]"}}
            ],
        )
        self.assertEqual(result["timeout"], 180)

    async def test_non_send_action_is_unchanged_even_with_video_parameter(self):
        result = await self.api.call_action("get_status", message=VIDEO)
        self.assertEqual(result["timeout"], 180)
        self.assertIs(result["api"], self.api)

    async def test_concurrent_ordinary_request_is_not_extended(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        await self.plugin.terminate()
        original_transport = self.original

        async def delayed_transport(api, action, **params):
            if action == "send_group_msg":
                entered.set()
                await release.wait()
            return await original_transport(api, action, **params)

        self.Api.call_action = delayed_transport
        await self.plugin.initialize()
        sending = asyncio.create_task(
            self.api.call_action("send_group_msg", message=VIDEO)
        )
        await entered.wait()
        status = await self.api.call_action("get_status")
        self.assertEqual(status["timeout"], 180)
        self.assertEqual(self.api._timeout_sec, 180)
        release.set()
        self.assertEqual((await sending)["timeout"], 1800)

    async def test_parameters_are_passed_without_timeout_fields_or_mutation(self):
        params = {"group_id": 123, "self_id": "123456789", "message": VIDEO}
        result = await self.api.call_action("send_group_msg", **params)
        self.assertEqual(result["params"], params)
        self.assertIs(result["params"]["message"], VIDEO)
        self.assertNotIn("timeout", result["params"])
        self.assertNotIn("_timeout", result["params"])

    async def test_existing_longer_timeout_is_preserved(self):
        api = self.Api(2500)
        result = await api.call_action("send_group_msg", message=VIDEO)
        self.assertEqual(result["timeout"], 2500)
        self.assertIs(result["api"], api)

    async def test_original_exception_is_preserved(self):
        await self.plugin.terminate()
        expected = RuntimeError("transport failure")

        async def raising(api, action, **params):
            raise expected

        self.Api.call_action = raising
        await self.plugin.initialize()
        with self.assertRaises(RuntimeError) as caught:
            await self.api.call_action("send_group_msg", message=VIDEO)
        self.assertIs(caught.exception, expected)
        self.assertEqual(self.api._timeout_sec, 180)

    async def test_double_initialize_does_not_stack_wrappers(self):
        wrapper = self.Api.call_action
        await self.plugin.initialize()
        self.assertIs(self.Api.call_action, wrapper)
        self.assertIs(wrapper.__wrapped__, self.original)

    async def test_termination_restores_original_and_is_idempotent(self):
        await self.plugin.terminate()
        self.assertIs(self.Api.call_action, self.original)
        await self.plugin.terminate()
        self.assertIs(self.Api.call_action, self.original)

    async def test_later_wrapper_is_preserved_and_guard_becomes_inactive(self):
        ours = self.Api.call_action

        @wraps(ours)
        async def other(api, action, **params):
            result = await ours(api, action, **params)
            result["other"] = True
            return result

        self.Api.call_action = other
        await self.plugin.terminate()
        self.assertIs(self.Api.call_action, other)
        result = await self.api.call_action("send_group_msg", message=VIDEO)
        self.assertEqual(result["timeout"], 180)
        self.assertTrue(result["other"])

    async def test_reload_replaces_direct_guard_and_old_termination_is_safe(self):
        new_plugin = self.Plugin(object(), {"video_timeout_sec": 2400})
        await new_plugin.initialize()
        self.assertIs(self.Api.call_action.__wrapped__, self.original)
        await self.plugin.terminate()
        self.assertEqual(
            (await self.api.call_action("send_msg", message=VIDEO))["timeout"], 2400
        )
        await new_plugin.terminate()
        self.assertIs(self.Api.call_action, self.original)

    async def test_config_bounds_and_invalid_values(self):
        for configured, expected in [
            (100, 180),
            (99999, 3600),
            (None, 1800),
            ("bad", 1800),
            (2400, 2400),
        ]:
            with self.subTest(configured=configured):
                plugin = self.Plugin(object(), {"video_timeout_sec": configured})
                self.assertEqual(plugin.video_timeout_sec, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
