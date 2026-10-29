"""Verified, serialized forwarding to the two existing native tools.

There is deliberately no backend timeout or automatic retry. The desktop mutex
is held until the backend exits; a caller must allow the backend's full budget.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys


@dataclass(frozen=True)
class Backend:
    executable: Path
    tool: str


BACKENDS = {
    "native": Backend(Path(r"E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeControlTool\XuanYuanNativeControlTool.exe"),
                      "xuanyuan-native-control"),
    "resource": Backend(Path(r"E:\XuanYuanDevPlatform\wzl编辑\bin\XuanYuanNativeResourceTool\XuanYuanNativeResourceTool.exe"),
                        "xuanyuan-native-resource"),
}
COMMANDS = {
    "game": frozenset(("game-inspect", "game-observe", "game-input")),
    "m2": frozenset(("inspect", "m2-start", "m2-stop", "m2-reload", "engine-parameter", "m2-client-build", "window-observe", "window-action", "m2-event-evidence")),
    "engine": frozenset(("inspect", "engine-preflight", "engine-controller-start", "engine-controller-stop", "window-observe", "window-action")),
    "launcher": frozenset(("launcher-save", "launcher-build", "window-observe", "window-action")),
    "editor": frozenset(("window-observe", "window-action")),
    "resource": frozenset(("import", "batch-import", "export", "batch-export")),
}
MUTEX_NAME = r"Local\XuanYuanSkillDesktop"
EVENT_COMMAND = "m2-event-evidence"
EVENT_TARGET = r"D:\Mirserver100\Mir200\M2Server.exe"
EVENT_SHA256 = "1D4D58A4C49EE97D2844FCB2BB31EA3E1F11E7FEDE4DBC857A3FE21979723F1A"


class RouterError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DesktopMutex:
    """Session-local cross-process lock, acquired with zero wait."""

    def __enter__(self):
        if os.name != "nt":
            raise RouterError("unsupported-platform", "Native desktop calls require Windows")
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        api.CreateMutexW.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        api.ReleaseMutex.restype = wintypes.BOOL
        api.CloseHandle.argtypes = (wintypes.HANDLE,)
        api.CloseHandle.restype = wintypes.BOOL
        handle = api.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            raise RouterError("desktop-lock-error", "Cannot create desktop mutex")
        outcome = api.WaitForSingleObject(handle, 0)
        if outcome != 0:
            # Abandoned ownership is uncertain. Release the newly acquired mutex
            # and require a fresh state inspection instead of starting an action.
            if outcome == 0x80:
                api.ReleaseMutex(handle)
            api.CloseHandle(handle)
            if outcome == 0x102:
                raise RouterError("desktop-busy", "Desktop is busy; no request was queued")
            if outcome == 0x80:
                raise RouterError("desktop-abandoned", "Previous desktop owner ended unexpectedly; inspect current state")
            raise RouterError("desktop-lock-error", "Cannot acquire desktop mutex")
        self.api, self.handle = api, handle
        return self

    def __exit__(self, *args):
        released = self.api.ReleaseMutex(self.handle)
        closed = self.api.CloseHandle(self.handle)
        if not released or not closed:
            raise RouterError("desktop-lock-error", "Cannot confirm desktop mutex release")


def _verified_backend(adapter: str, command: str | None):
    key = "resource" if adapter == "resource" else "native"
    backend = BACKENDS[key]
    try:
        executable = backend.executable.resolve(strict=True)
        directory = backend.executable.parent.resolve(strict=True)
        manifest = json.loads((directory / "tool.manifest.json").read_text(encoding="utf-8-sig"))
        if not isinstance(manifest, dict) or type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1:
            raise RouterError("manifest-invalid", "Unsupported tool manifest")
        if manifest.get("tool") != backend.tool:
            raise RouterError("manifest-identity", "Tool manifest identity does not match fixed backend")
        entrypoint = manifest.get("entrypoint")
        if (not isinstance(entrypoint, str) or entrypoint != backend.executable.name
                or executable.parent != directory
                or (directory / entrypoint).resolve(strict=True) != executable):
            raise RouterError("manifest-entrypoint", "Manifest entrypoint does not match fixed backend")
        version = manifest.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise RouterError("manifest-version", "Tool manifest has no stable version")
        expected_hash = manifest.get("executableSha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
            raise RouterError("manifest-hash", "Tool manifest SHA256 is invalid")
        digest = hashlib.sha256()
        with executable.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_hash = digest.hexdigest().upper()
        if actual_hash != expected_hash.upper():
            raise RouterError("manifest-hash", "Backend executable SHA256 does not match manifest")
        advertised = manifest.get("operationScope" if key == "resource" else "commands")
        if not isinstance(advertised, list) or any(not isinstance(item, str) for item in advertised):
            raise RouterError("manifest-commands", "Tool manifest command list is invalid")
        if command == EVENT_COMMAND and tuple(map(int, version.split("."))) < (1, 1, 12):
            raise RouterError("event-unavailable", "m2-event-evidence requires Native Control 1.1.12 or newer and a manifest declaring m2-event-evidence")
        if command is not None and command not in advertised:
            raise RouterError("manifest-commands", "Requested command is absent from tool manifest")
        if adapter == "game" and (tuple(map(int, version.split("."))) < (1, 1, 8)
                                  or not COMMANDS["game"].issubset(advertised)):
            raise RouterError("game-unavailable", "Game adapter requires Native Control 1.1.8 and all game commands")
        if (command in COMMANDS["editor"] or adapter == "editor") and (
                tuple(map(int, version.split("."))) < (1, 1, 9)
                or not COMMANDS["editor"].issubset(advertised)):
            raise RouterError("window-unavailable", "Native window adapter requires Native Control 1.1.9 and both window commands")
        return key, backend, executable, version, actual_hash
    except RouterError:
        raise
    except (OSError, ValueError, TypeError):
        raise RouterError("manifest-invalid", "Cannot verify fixed backend manifest and executable") from None


def _backend_call(executable: Path, key: str, payload: bytes | None):
    suffix = (["run", "--request", "-"] if payload is not None else
              (["meta", "capabilities"] if key == "resource" else ["capabilities"]))
    try:
        process = subprocess.Popen([str(executable), *suffix], cwd=str(executable.parent),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        raise RouterError("backend-start", "Cannot start verified backend") from None
    try:
        stdout, _stderr = process.communicate(input=payload)
    except BaseException:
        # Do not kill, retry the request, or release the desktop while the child
        # may still be operating. Re-enter communicate only to drain/wait.
        while process.poll() is None:
            try:
                process.communicate()
            except BaseException:
                continue
        raise RouterError("backend-interrupted", "Backend exited after interrupted observation; outcome unknown, inspect state before retry") from None
    try:
        response = json.loads(stdout.decode("utf-8-sig"))
        if not isinstance(response, dict):
            raise ValueError("non-object response")
    except (UnicodeError, ValueError, TypeError):
        return process.returncode, None
    return process.returncode, response


def _validate_event_request(request):
    """Keep the fixed read-only profile from accepting arbitrary memory inputs."""
    if (set(request) != {"schemaVersion", "command", "arguments", "policy"}
            or type(request.get("schemaVersion")) is not int or request["schemaVersion"] != 1):
        raise RouterError("invalid-request", "m2-event-evidence requires schemaVersion 1 and exactly command, arguments, and policy")
    arguments, policy = request.get("arguments"), request.get("policy")
    if (not isinstance(arguments, dict)
            or set(arguments) != {"pid", "expectedExecutable", "expectedSha256", "profile", "outputRoot"}
            or not isinstance(policy, dict) or set(policy) != {"allowedWriteRoots"}):
        raise RouterError("invalid-request", "m2-event-evidence requires the fixed profile argument and output policy fields")
    target, digest = arguments["expectedExecutable"], arguments["expectedSha256"]
    if (type(arguments["pid"]) is not int or not 0 < arguments["pid"] <= 0xFFFFFFFF
            or not isinstance(target, str) or ntpath.normcase(ntpath.normpath(target)) != ntpath.normcase(EVENT_TARGET)
            or not isinstance(digest, str) or digest.upper() != EVENT_SHA256
            or arguments["profile"] != "custom-monster-summon-v1"):
        raise RouterError("invalid-request", "m2-event-evidence requires a current PID and the pinned M2Server.exe path, SHA256, and custom-monster-summon-v1 profile")
    output_root, roots = arguments["outputRoot"], policy["allowedWriteRoots"]
    paths = [output_root, *roots] if isinstance(roots, list) else []
    if (not isinstance(roots, list) or not roots or not paths
            or any(not isinstance(path, str) or not path.strip() or not ntpath.isabs(path)
                   or not ntpath.splitdrive(path)[0] for path in paths)):
        raise RouterError("invalid-request", "m2-event-evidence requires absolute outputRoot and nonempty policy.allowedWriteRoots")


def _dispatch_unlocked(adapter: str, request, capabilities: bool, cache=None):
    if adapter not in COMMANDS:
        raise RouterError("invalid-adapter", "Unknown adapter")
    command, payload = None, None
    if not capabilities:
        if not isinstance(request, dict) or not isinstance(request.get("command"), str):
            raise RouterError("invalid-request", "Request must be a JSON object with a string command")
        command = request["command"]
        if command not in COMMANDS[adapter]:
            raise RouterError("adapter-command", "Requested command does not belong to selected adapter")
        if command == EVENT_COMMAND:
            _validate_event_request(request)
        try:
            payload = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise RouterError("invalid-request", "Request is not valid UTF-8 JSON") from None
    key, _backend, executable, version, digest = _verified_backend(adapter, command)
    cache_key = (str(executable), digest)
    if capabilities and cache is not None and cache_key in cache:
        exit_code, response = cache[cache_key]
    else:
        exit_code, response = _backend_call(executable, key, payload)
        if capabilities and cache is not None:
            cache[cache_key] = (exit_code, response)
    valid_protocol = response is not None
    if valid_protocol:
        version_field = "providerVersion" if key == "resource" else "version"
        valid_protocol = response.get(version_field) == version
        if key == "resource":
            valid_protocol = valid_protocol and response.get("provider") == _backend.tool
        if capabilities:
            advertised = response.get("operations" if key == "resource" else "commands")
            required_commands = COMMANDS[adapter]
            if adapter == "m2" and tuple(map(int, version.split("."))) < (1, 1, 12):
                required_commands = required_commands - {EVENT_COMMAND}
            valid_protocol = (valid_protocol and isinstance(advertised, list)
                              and all(isinstance(item, str) for item in advertised)
                              and required_commands.issubset(advertised))
        else:
            valid_protocol = valid_protocol and type(response.get("ok")) is bool
    backend_ok = (response.get("ok", True) is True if capabilities else response.get("ok") is True) if response is not None else False
    ok = exit_code == 0 and valid_protocol and backend_ok
    result = {"schemaVersion": 1, "adapter": adapter, "toolVersion": version,
              "toolSha256": digest, "exitCode": exit_code, "ok": ok, "backendResponse": response}
    if not valid_protocol:
        result["error"] = {"code": "backend-protocol", "message": "Backend response does not match verified version and adapter contract; inspect state before retry"}
    return result


def dispatch(adapter: str, request=None, *, capabilities: bool = False):
    with DesktopMutex():
        return _dispatch_unlocked(adapter, request, capabilities)


def _error_response(adapter, error: RouterError):
    return {"schemaVersion": 1, "adapter": adapter, "toolVersion": None, "toolSha256": None,
            "exitCode": None, "ok": False, "backendResponse": None,
            "error": {"code": error.code, "message": str(error)}}


def all_capabilities():
    responses, cache = {}, {}
    with DesktopMutex():
        for adapter in COMMANDS:
            try:
                responses[adapter] = _dispatch_unlocked(adapter, None, True, cache)
            except RouterError as error:
                responses[adapter] = _error_response(adapter, error)
    return {"schemaVersion": 1, "ok": all(value["ok"] for value in responses.values()), "adapters": responses}


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Forward original requests to verified native tool adapters")
    parser.add_argument("--adapter", choices=tuple(COMMANDS))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request", help="Original request JSON file, or - for UTF-8 stdin")
    mode.add_argument("--capabilities", action="store_true", help="Query selected adapter or all adapters")
    args = parser.parse_args(argv)
    try:
        if args.capabilities:
            result = dispatch(args.adapter, capabilities=True) if args.adapter else all_capabilities()
        else:
            if args.adapter is None:
                raise RouterError("invalid-adapter", "--adapter is required with --request")
            try:
                content = sys.stdin.read() if args.request == "-" else Path(args.request).read_text(encoding="utf-8-sig")
                request = json.loads(content.lstrip("\ufeff"))
            except (OSError, UnicodeError, ValueError):
                raise RouterError("invalid-request", "Cannot read request as UTF-8 JSON") from None
            result = dispatch(args.adapter, request)
    except RouterError as error:
        result = _error_response(args.adapter, error)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
