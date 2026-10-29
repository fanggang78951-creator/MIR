"""Event route contract tests; no GUI or real backend process is started."""

from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "skill" / "xuanyuan-native-control" / "scripts" / "invoke.py"
TARGET = r"D:\Mirserver100\Mir200\M2Server.exe"
TARGET_SHA256 = "1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A"
LEGACY_COMMANDS = ["game-inspect", "game-observe", "game-input", "inspect", "m2-start", "m2-stop",
                   "m2-reload", "engine-parameter", "m2-client-build", "engine-preflight",
                   "engine-controller-start", "engine-controller-stop", "launcher-save", "launcher-build",
                   "window-observe", "window-action"]


class EventSkillRouterTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("event_skill_router_under_test", SCRIPT)
        self.router = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.router
        spec.loader.exec_module(self.router)
        temporary = tempfile.TemporaryDirectory(prefix="xuanyuan-event-router-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        executable = self.directory / "XuanYuanNativeControlTool.exe"
        executable.write_bytes(b"trusted event-route test backend")
        self.manifest = {"schemaVersion": 1, "tool": "xuanyuan-native-control", "version": "1.1.12",
                         "entrypoint": executable.name,
                         "executableSha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                         "commands": LEGACY_COMMANDS + ["m2-event-evidence"]}
        self.write_manifest()
        self.patch("BACKENDS", {"native": self.router.Backend(executable, "xuanyuan-native-control")})
        self.patch("DesktopMutex", nullcontext)
        self.backend = self.patch("_backend_call", mock.Mock(side_effect=self.respond))

    def patch(self, name, value):
        patcher = mock.patch.object(self.router, name, value)
        patched = patcher.start()
        self.addCleanup(patcher.stop)
        return patched

    def write_manifest(self, **changes):
        self.manifest.update(changes)
        (self.directory / "tool.manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def respond(self, executable, key, payload):
        body = {"schemaVersion": 1, "version": self.manifest["version"]}
        if payload is None:
            body["commands"] = self.manifest["commands"]
        else:
            body.update(ok=True, data={"readOnly": True})
        return 0, body

    @staticmethod
    def request():
        return {"schemaVersion": 1, "command": "m2-event-evidence",
                "arguments": {"pid": 4312, "expectedExecutable": TARGET,
                              "expectedSha256": TARGET_SHA256, "profile": "custom-monster-summon-v1",
                              "outputRoot": r"D:\event-evidence\run-1"},
                "policy": {"allowedWriteRoots": [r"D:\event-evidence"]}}

    def assert_rejected(self, request, code="invalid-request", adapter="m2"):
        with self.assertRaises(self.router.RouterError) as raised:
            self.router.dispatch(adapter, request)
        self.assertEqual(raised.exception.code, code)
        self.backend.assert_not_called()

    def test_m2_event_request_preserves_original_json_for_verified_backend(self):
        request = self.request()
        result = self.router.dispatch("m2", request)
        self.assertTrue(result["ok"])
        self.assertEqual(result["toolVersion"], "1.1.12")
        self.assertEqual(json.loads(self.backend.call_args.args[2]), request)

    def test_other_adapters_reject_event_command_before_backend_launch(self):
        for adapter in ("game", "engine", "launcher", "editor", "resource"):
            with self.subTest(adapter=adapter):
                self.assert_rejected(self.request(), "adapter-command", adapter)

    def test_event_requires_1_1_12_even_when_old_manifest_advertises_it(self):
        for version in ("1.1.8", "1.1.9"):
            with self.subTest(version=version):
                self.write_manifest(version=version)
                self.assert_rejected(self.request(), "event-unavailable")

    def test_1_1_10_event_carrier_is_rejected_before_backend_launch(self):
        self.write_manifest(version="1.1.10")
        self.assert_rejected(self.request(), "event-unavailable")

    def test_1_1_11_without_shared_successor_contract_is_rejected_before_backend_launch(self):
        self.write_manifest(version="1.1.11")
        self.assert_rejected(self.request(), "event-unavailable")

    def test_event_requires_manifest_declaration(self):
        self.write_manifest(commands=LEGACY_COMMANDS)
        self.assert_rejected(self.request(), "manifest-commands")

    def test_legacy_m2_requests_and_capabilities_still_work_before_1_1_12(self):
        for version in ("1.1.9", "1.1.10", "1.1.11"):
            with self.subTest(version=version):
                self.write_manifest(version=version, commands=LEGACY_COMMANDS)
                result = self.router.dispatch("m2", {"schemaVersion": 1, "command": "inspect"})
                self.assertTrue(result["ok"])
                self.assertTrue(self.router.dispatch("m2", capabilities=True)["ok"])

    def test_1_1_12_m2_capabilities_require_event_command_in_response(self):
        self.backend.side_effect = None
        self.backend.return_value = (0, {"version": "1.1.12", "commands": LEGACY_COMMANDS})
        result = self.router.dispatch("m2", capabilities=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "backend-protocol")

    def test_schema_and_exact_request_shape_are_checked_before_launch(self):
        cases = []
        for field in ("schemaVersion", "arguments", "policy"):
            value = self.request()
            del value[field]
            cases.append(value)
        for schema in (True, "1", 2):
            value = self.request()
            value["schemaVersion"] = schema
            cases.append(value)
        for container, extra in ((None, "requestId"), ("arguments", "address"), ("policy", "allowMemoryWrite")):
            value = self.request()
            (value if container is None else value[container])[extra] = 1
            cases.append(value)
        for value in cases:
            with self.subTest(request=value):
                self.assert_rejected(value)

    def test_fixed_target_profile_pid_and_output_policy_are_enforced(self):
        replacements = [("pid", True), ("pid", 0), ("pid", "4312"),
                        ("expectedExecutable", r"D:\other\M2Server.exe"),
                        ("expectedSha256", "0" * 64), ("profile", "another-profile"),
                        ("outputRoot", ""), ("outputRoot", "relative-output")]
        for name, replacement in replacements:
            with self.subTest(name=name, replacement=replacement):
                value = self.request()
                value["arguments"][name] = replacement
                self.assert_rejected(value)
        for roots in (None, [], "D:\\event-evidence", [""], ["relative-root"]):
            with self.subTest(roots=roots):
                value = self.request()
                value["policy"]["allowedWriteRoots"] = roots
                self.assert_rejected(value)

    def test_case_insensitive_windows_target_and_hash_are_forwarded_unchanged(self):
        value = self.request()
        value["arguments"]["expectedExecutable"] = TARGET.lower()
        value["arguments"]["expectedSha256"] = TARGET_SHA256.lower()
        result = self.router.dispatch("m2", value)
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(self.backend.call_args.args[2]), value)


if __name__ == "__main__":
    unittest.main()
