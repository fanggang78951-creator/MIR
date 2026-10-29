"""Thin router tests; backend processes are fakes and never open a GUI."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "xuanyuan-native-control" / "scripts" / "invoke.py"


class SkillRouterTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Unified skill router has not been implemented")
        spec = importlib.util.spec_from_file_location("skill_router_under_test", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)
        folder = tempfile.TemporaryDirectory(prefix="xuanyuan-router-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        specs = {}
        for name, filename, tool, version in (
            ("native", "XuanYuanNativeControlTool.exe", "xuanyuan-native-control", "1.1.9"),
            ("resource", "XuanYuanNativeResourceTool.exe", "xuanyuan-native-resource", "1.0.1"),
        ):
            location = self.root / name
            location.mkdir()
            exe = location / filename
            exe.write_bytes((name + " trusted test bytes").encode())
            manifest = {
                "schemaVersion": 1, "tool": tool, "version": version, "entrypoint": filename,
                "executableSha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                "commands": ["game-inspect", "game-observe", "game-input", "inspect", "m2-start", "m2-stop",
                             "m2-reload", "engine-parameter", "m2-client-build", "engine-preflight",
                             "engine-controller-start", "engine-controller-stop", "launcher-save", "launcher-build",
                             "window-observe", "window-action"],
                "operationScope": ["import", "batch-import", "export", "batch-export"],
            }
            (location / "tool.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            specs[name] = self.module.Backend(exe, tool)
        self.patch("BACKENDS", specs)
        self.state = {"held": False, "busy": False, "calls": [], "releases": 0}
        state = self.state
        module = self.module
        self.real_mutex = module.DesktopMutex

        class FakeMutex:
            def __enter__(self):
                if state["busy"]:
                    raise module.RouterError("desktop-busy", "Desktop is busy")
                state["held"] = True
                return self

            def __exit__(self, *args):
                state["held"] = False
                state["releases"] += 1

        self.patch("DesktopMutex", FakeMutex)
        self.process()

    def patch(self, name, value):
        patcher = mock.patch.object(self.module, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def process(self, stdout=None, stderr=b"", code=0):
        state = self.state
        owner = self

        class FakeProcess:
            pid = 4312
            returncode = code

            def communicate(self, input=None):
                owner.assertTrue(state["held"], "desktop lock must cover backend completion")
                state["calls"][-1]["input"] = input
                output = stdout
                argv = state["calls"][-1]["argv"]
                resource = "Resource" in argv[0]
                if isinstance(output, dict):
                    output = output["resource" if resource else "native"]
                if output is None:
                    body = ({"schemaVersion": 1, "provider": "xuanyuan-native-resource", "providerVersion": "1.0.1"}
                            if resource else {"version": "1.1.9"})
                    if "run" in argv:
                        body.update(schemaVersion=1, ok=True, data={"中文": "背包"})
                    elif resource:
                        body["operations"] = ["import", "batch-import", "export", "batch-export"]
                    else:
                        body["commands"] = ["game-inspect", "game-observe", "game-input", "inspect", "m2-start", "m2-stop",
                                            "m2-reload", "engine-parameter", "m2-client-build", "engine-preflight",
                                            "engine-controller-start", "engine-controller-stop", "launcher-save", "launcher-build",
                                            "window-observe", "window-action"]
                    output = json.dumps(body, ensure_ascii=False).encode("utf-8")
                return output, stderr

        def popen(argv, **kwargs):
            owner.assertTrue(state["held"], "desktop lock must precede process launch")
            state["calls"].append({"argv": argv, "kwargs": kwargs})
            return FakeProcess()

        patcher = mock.patch.object(self.module.subprocess, "Popen", popen)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def request(command="game-input"):
        return {"schemaVersion": 1, "requestId": "测试-1", "command": command,
                "arguments": {"action": "key", "key": "B"}, "policy": {"allowedWriteRoots": ["D:\\任务"]}}

    def edit_manifest(self, key="native", **changes):
        path = self.module.BACKENDS[key].executable.parent / "tool.manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(changes)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_utf8_original_request_and_wrapped_backend_response(self):
        original = self.request()
        result = self.module.dispatch("game", original)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["adapter"], "game")
        self.assertEqual(result["toolVersion"], "1.1.9")
        self.assertEqual(len(result["toolSha256"]), 64)
        self.assertEqual(result["exitCode"], 0)
        self.assertEqual(result["backendResponse"], {"schemaVersion": 1, "version": "1.1.9", "ok": True, "data": {"中文": "背包"}})
        call = self.state["calls"][0]
        self.assertEqual(call["argv"], [str(self.module.BACKENDS["native"].executable), "run", "--request", "-"])
        self.assertEqual(json.loads(call["input"].decode("utf-8")), original)
        self.assertIs(call["kwargs"]["shell"], False)
        self.assertFalse(self.state["held"])
        self.assertEqual(self.state["releases"], 1)

    def test_adapter_mismatch_and_arbitrary_commands_cannot_spawn(self):
        for adapter, command in [("game", "m2-stop"), ("m2", "game-input"), ("engine", "launcher-build"),
                                 ("launcher", "inspect"), ("resource", "engine-controller-start"), ("m2", "powershell.exe")]:
            with self.subTest(adapter=adapter, command=command):
                with self.assertRaisesRegex(self.module.RouterError, "command"):
                    self.module.dispatch(adapter, self.request(command))
                self.assertEqual(self.state["calls"], [])

    def test_request_object_and_string_command_are_required(self):
        for payload in [None, True, [], "game-input", {"command": 4}, {"command": None}]:
            with self.subTest(payload=payload):
                with self.assertRaises(self.module.RouterError):
                    self.module.dispatch("game", payload)
                self.assertEqual(self.state["calls"], [])

    def test_live_hash_is_rechecked_on_every_invocation(self):
        self.module.dispatch("m2", self.request("inspect"))
        self.module.BACKENDS["native"].executable.write_bytes(b"changed executable")
        with self.assertRaisesRegex(self.module.RouterError, "SHA256"):
            self.module.dispatch("m2", self.request("inspect"))
        self.assertEqual(len(self.state["calls"]), 1)

    def test_entrypoint_tool_hash_and_version_manifest_gates(self):
        for changes in [{"entrypoint": "../other.exe"}, {"entrypoint": "C:\\other.exe"},
                        {"entrypoint": "child/../XuanYuanNativeControlTool.exe"}, {"tool": "other-tool"},
                        {"executableSha256": "not-a-hash"}, {"version": None}]:
            with self.subTest(changes=changes):
                self.edit_manifest(**changes)
                with self.assertRaises(self.module.RouterError):
                    self.module.dispatch("m2", self.request("inspect"))
                self.assertEqual(self.state["calls"], [])

    def test_game_requires_stable_release_and_all_game_commands(self):
        for changes in [{"version": "1.1.6"}, {"version": "1.1.8-rc1"}, {"version": "1.1.8", "commands": ["inspect", "game-inspect"]}]:
            with self.subTest(changes=changes):
                self.edit_manifest(**changes)
                with self.assertRaises(self.module.RouterError):
                    self.module.dispatch("game", self.request("game-inspect"))
                self.assertEqual(self.state["calls"], [])

    def test_manifest_must_advertise_command(self):
        self.edit_manifest(commands=["inspect"])
        with self.assertRaises(self.module.RouterError):
            self.module.dispatch("m2", self.request("m2-stop"))
        self.assertEqual(self.state["calls"], [])

    def test_resource_uses_existing_resource_executable(self):
        result = self.module.dispatch("resource", self.request("export"))
        self.assertIs(result["ok"], True)
        self.assertEqual(result["toolVersion"], "1.0.1")
        self.assertEqual(self.state["calls"][0]["argv"][0], str(self.module.BACKENDS["resource"].executable))

    def test_native_window_requests_route_all_native_adapters_to_control(self):
        self.edit_manifest(version="1.1.9", commands=["window-observe", "window-action"])
        self.process(stdout=b'{"version":"1.1.9","ok":true,"data":{"snapshotId":"observed-1"}}')
        for adapter in ("m2", "engine", "launcher", "editor"):
            for command in ("window-observe", "window-action"):
                with self.subTest(adapter=adapter, command=command):
                    request = {"schemaVersion": 1, "requestId": "native-window-1", "command": command,
                               "arguments": {"pid": 32096, "expectedExecutable": "D:\\Mirserver100\\Mir200\\M2Server.exe"}}
                    result = self.module.dispatch(adapter, request)
                    self.assertIs(result["ok"], True)
                    self.assertEqual(result["toolVersion"], "1.1.9")
                    call = self.state["calls"][-1]
                    self.assertEqual(call["argv"][0], str(self.module.BACKENDS["native"].executable))
                    self.assertEqual(json.loads(call["input"].decode("utf-8")), request)
        self.assertEqual(self.state["releases"], 8)

    def test_game_and_resource_cannot_forward_native_window_requests(self):
        for adapter in ("game", "resource"):
            for command in ("window-observe", "window-action"):
                with self.subTest(adapter=adapter, command=command):
                    with self.assertRaises(self.module.RouterError) as error:
                        self.module.dispatch(adapter, self.request(command))
                    self.assertEqual(error.exception.code, "adapter-command")
                    self.assertEqual(self.state["calls"], [])

    def test_editor_rejects_resource_and_game_commands_without_spawn(self):
        for command in ("import", "export", "game-input", "m2-stop"):
            with self.subTest(command=command):
                with self.assertRaises(self.module.RouterError) as error:
                    self.module.dispatch("editor", self.request(command))
                self.assertEqual(error.exception.code, "adapter-command")
                self.assertEqual(self.state["calls"], [])

    def test_native_window_requires_new_release_and_both_window_commands(self):
        for version, commands in (("1.1.8", ["window-observe", "window-action"]),
                                  ("1.1.9", ["window-observe"]),
                                  ("1.1.9", ["window-action"])):
            with self.subTest(version=version, commands=commands):
                self.edit_manifest(version=version, commands=commands)
                with self.assertRaises(self.module.RouterError) as error:
                    self.module.dispatch("m2", self.request(commands[0]))
                self.assertEqual(error.exception.code, "window-unavailable")
                self.assertEqual(self.state["calls"], [])

    def test_failure_status_or_nonzero_exit_cannot_become_success(self):
        for stdout, code in [(b'{"ok":false,"error":{"message":"denied"}}', 1), (b'{"ok":false}', 0),
                             (b'{"ok":true}', 2), (b'{"ok":"false"}', 0)]:
            with self.subTest(stdout=stdout, code=code):
                self.process(stdout=stdout, stderr=b"sensitive business data", code=code)
                result = self.module.dispatch("m2", self.request("inspect"))
                self.assertIs(result["ok"], False)
                self.assertEqual(result["exitCode"], code)
                self.assertEqual(result["backendResponse"], json.loads(stdout))
                self.assertNotIn("sensitive", json.dumps(result))

    def test_invalid_backend_json_is_not_echoed(self):
        for stdout in [b"", b"secret raw output", b"[]", b"null", b"\xff"]:
            with self.subTest(stdout=stdout):
                self.process(stdout=stdout, stderr=b"private stderr", code=0)
                result = self.module.dispatch("m2", self.request("inspect"))
                self.assertIs(result["ok"], False)
                self.assertIsNone(result["backendResponse"])
                self.assertEqual(result["error"]["code"], "backend-protocol")
                self.assertNotIn("secret", json.dumps(result))
                self.assertNotIn("private", json.dumps(result))

    def test_busy_mutex_denies_before_spawn(self):
        self.state["busy"] = True
        with self.assertRaises(self.module.RouterError) as error:
            self.module.dispatch("game", self.request())
        self.assertEqual(error.exception.code, "desktop-busy")
        self.assertEqual(self.state["calls"], [])

    def test_capability_arguments_do_not_create_operation_request(self):
        for adapter, suffix in [("game", ["capabilities"]), ("resource", ["meta", "capabilities"])]:
            with self.subTest(adapter=adapter):
                result = self.module.dispatch(adapter, capabilities=True)
                self.assertIs(result["ok"], True)
                self.assertEqual(self.state["calls"][-1]["argv"][1:], suffix)
                self.assertIsNone(self.state["calls"][-1]["input"])

    def test_all_capabilities_queries_two_backends_under_one_lock(self):
        result = self.module.all_capabilities()
        self.assertIs(result["ok"], True)
        self.assertEqual(set(result["adapters"]), {"game", "m2", "engine", "launcher", "editor", "resource"})
        self.assertEqual(len(self.state["calls"]), 2)
        self.assertEqual(self.state["releases"], 1)
        self.assertEqual(result["adapters"]["engine"]["adapter"], "engine")

    def test_cli_utf8_input_and_backend_failure_exit(self):
        self.process(stdout=b'{"ok":false,"error":{"message":"denied"}}', code=1)
        outgoing = io.StringIO()
        with mock.patch.object(self.module.sys, "stdin", io.StringIO(json.dumps(self.request("inspect"), ensure_ascii=False))), \
             mock.patch.object(self.module.sys, "stdout", outgoing):
            code = self.module.main(["--adapter", "m2", "--request", "-"])
        self.assertNotEqual(code, 0)
        self.assertIs(json.loads(outgoing.getvalue())["ok"], False)
        self.assertTrue(self.state["calls"])

    def test_cli_malformed_input_never_echoes_payload(self):
        outgoing = io.StringIO()
        with mock.patch.object(self.module.sys, "stdin", io.StringIO("private malformed input")), \
             mock.patch.object(self.module.sys, "stdout", outgoing):
            code = self.module.main(["--adapter", "game", "--request", "-"])
        self.assertNotEqual(code, 0)
        self.assertNotIn("private", outgoing.getvalue())
        self.assertEqual(json.loads(outgoing.getvalue())["error"]["code"], "invalid-request")
        self.assertEqual(self.state["calls"], [])

    def test_old_native_game_is_denied_while_other_capabilities_are_reported(self):
        self.edit_manifest(version="1.1.6", commands=["inspect"])
        self.process(stdout={
            "native": b'{"version":"1.1.6","commands":["inspect","m2-start","m2-stop","m2-reload","engine-parameter","m2-client-build","engine-preflight","engine-controller-start","engine-controller-stop","launcher-save","launcher-build"]}',
            "resource": b'{"schemaVersion":1,"provider":"xuanyuan-native-resource","providerVersion":"1.0.1","operations":["import","batch-import","export","batch-export"]}',
        })
        result = self.module.all_capabilities()
        self.assertIs(result["ok"], False)
        self.assertEqual(result["adapters"]["game"]["error"]["code"], "game-unavailable")
        self.assertIs(result["adapters"]["m2"]["ok"], False)
        self.assertEqual(result["adapters"]["m2"]["error"]["code"], "backend-protocol")
        self.assertEqual(result["adapters"]["editor"]["error"]["code"], "window-unavailable")
        self.assertIs(result["adapters"]["resource"]["ok"], True)
        self.assertEqual(len(self.state["calls"]), 2)

    def test_spawn_error_is_sanitized(self):
        with mock.patch.object(self.module.subprocess, "Popen", side_effect=OSError("private backend path")):
            with self.assertRaises(self.module.RouterError) as error:
                self.module.dispatch("m2", self.request("inspect"))
        self.assertEqual(error.exception.code, "backend-start")
        self.assertNotIn("private", str(error.exception))
        self.assertFalse(self.state["held"])

    def test_interrupted_observation_keeps_lock_until_child_exits_without_relaunch(self):
        state, owner = self.state, self
        calls = []

        class InterruptedProcess:
            pid = 1234
            returncode = None
            communicated = 0

            def communicate(self, input=None):
                owner.assertTrue(state["held"])
                self.communicated += 1
                if self.communicated == 1:
                    raise KeyboardInterrupt()
                self.returncode = 0
                return b'{"ok":true}', b""

            def poll(self):
                return self.returncode

        def popen(*args, **kwargs):
            calls.append(args)
            return InterruptedProcess()

        with mock.patch.object(self.module.subprocess, "Popen", popen):
            with self.assertRaises(self.module.RouterError) as error:
                self.module.dispatch("m2", self.request("inspect"))
        self.assertEqual(error.exception.code, "backend-interrupted")
        self.assertEqual(len(calls), 1)
        self.assertEqual(state["releases"], 1)

    @unittest.skipUnless(os.name == "nt", "Win32 mutex requires Windows")
    def test_real_win32_mutex_denies_other_thread_and_releases(self):
        result = []

        def contender():
            try:
                with self.real_mutex():
                    result.append("unexpected acquisition")
            except self.module.RouterError as error:
                result.append(error.code)

        with mock.patch.object(self.module, "MUTEX_NAME", "Local\\XuanYuanRouterTest-" + self.root.name):
            with self.real_mutex():
                thread = threading.Thread(target=contender)
                thread.start()
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(result, ["desktop-busy"])
            with self.real_mutex():
                pass

    def test_run_response_version_must_match_manifest(self):
        for adapter, body in [("m2", {"ok": True, "version": "1.1.6"}),
                              ("m2", {"ok": True}),
                              ("resource", {"ok": True, "providerVersion": "1.0.0", "provider": "xuanyuan-native-resource"}),
                              ("resource", {"ok": True, "providerVersion": "1.0.1", "provider": "wrong-provider"})]:
            with self.subTest(adapter=adapter, body=body):
                self.process(stdout=json.dumps(body).encode())
                result = self.module.dispatch(adapter, self.request("export" if adapter == "resource" else "inspect"))
                self.assertIs(result["ok"], False)
                self.assertEqual(result["error"]["code"], "backend-protocol")
                self.assertEqual(result["backendResponse"], body)

    def test_capability_response_version_and_operations_are_validated(self):
        for adapter, body in [
            ("game", {"version": "1.1.6", "commands": ["game-inspect", "game-observe", "game-input"]}),
            ("game", {"version": "1.1.9", "commands": []}),
            ("game", {"version": "1.1.9", "commands": "game-inspect"}),
            ("game", {"version": "1.1.9", "commands": [{"command": "game-input"}]}),
            ("engine", {"version": "1.1.9", "commands": ["inspect"]}),
            ("editor", {"version": "1.1.9", "commands": ["window-observe"]}),
            ("resource", {"provider": "xuanyuan-native-resource", "providerVersion": "1.0.0", "operations": ["import", "batch-import", "export", "batch-export"]}),
            ("resource", {"provider": "xuanyuan-native-resource", "providerVersion": "1.0.1", "operations": ["export"]}),
        ]:
            with self.subTest(adapter=adapter, body=body):
                self.process(stdout=json.dumps(body).encode())
                result = self.module.dispatch(adapter, capabilities=True)
                self.assertIs(result["ok"], False)
                self.assertEqual(result["error"]["code"], "backend-protocol")
                self.assertEqual(result["backendResponse"], body)


if __name__ == "__main__":
    unittest.main()
