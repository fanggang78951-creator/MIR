# XY UI Toolkit Phase 2 Client Inspector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and stage a read-only Delphi client plugin plus Node CLI that exports the live LFM2 UI control tree without changing gameplay or UI behavior.

**Architecture:** A Delphi 7 plugin uses the supplied 3672-byte-compatible Client API and recursively reads `DStateWin`, `DItemBag`, and other named roots. Version 1 writes atomic JSON snapshots into the toolkit directory; the Node CLI requests, validates, filters, and diffs snapshots. Runtime mutation and named-pipe commands remain disabled until the read-only probe is verified in a client.

**Tech Stack:** Delphi 7 Win32 DLL, supplied `ClientAPI.pas` and `ClientType.pas`, Node.js 24 ESM, built-in `node:test`.

---

## Task 1: Stage Compatible Delphi Sources

**Files:**
- Create: `D:\MirServer\AI_Handoff\UI\XY_UI_Toolkit\client-inspector\plugin\PlugClient.dpr`
- Create: `D:\MirServer\AI_Handoff\UI\XY_UI_Toolkit\client-inspector\plugin\PlugMain.pas`
- Copy: supplied `Common\ClientAPI.pas` and `Common\ClientType.pas`

- [ ] Copy the exact API units from `D:\素材文件夹\全新聆风\LFM2[20260530]\API插件\客户端插件\Delphi\Common` into the isolated plugin source directory.
- [ ] Add `CInit` size validation that writes a probe record and returns `SizeOf(TClientAPI)` without installing hooks on mismatch.
- [ ] Compile with `D:\迅雷下载\delphi_7_ent_en\Install\program files\Borland\Delphi7\Bin\DCC32.EXE`.
- [ ] Verify the DLL exports only `CInit` and `CUnInit` and remains outside production folders.

## Task 2: Read-Only Control Snapshot Writer

**Files:**
- Modify: `client-inspector\plugin\PlugMain.pas`
- Create: `client-inspector\plugin\JsonWriter.pas`

- [ ] Hook initialization and draw-scene callbacks while always chaining the previous callbacks first.
- [ ] Resolve `GameInterfaceAPI.DStateWin`, `DItemBag`, `DBottomLeft`, `DBottomCenter`, and `DBottomRight`.
- [ ] Recursively export name, parent, left, top, width, height, visible, enabled, image indices, and child count.
- [ ] Escape JSON strings and write a temporary file before renaming it to `client-inspector\runtime\latest.json`.
- [ ] Do not call any API setter or install any click handler.
- [ ] Compile and statically scan the source for forbidden setter/event calls.

## Task 3: Client Inspector CLI

**Files:**
- Create: `src/client-snapshot.mjs`
- Create: `bin/xy-client.mjs`
- Create: `tests/client-snapshot.test.mjs`
- Modify: `package.json`

- [ ] Write failing tests for snapshot schema validation, exact-name lookup, subtree output, and snapshot diff.
- [ ] Implement `xy-client status`, `xy-client tree --root DStateWin`, `xy-client get DStateWin`, and `xy-client diff before.json after.json`.
- [ ] Reject malformed or stale snapshot files with exit code 5.
- [ ] Run the full Node test suite.

## Task 4: Isolated Integration Verification

- [ ] Verify the existing compatibility probe result remains `3672/3672`.
- [ ] Compile the read-only plugin to `client-inspector\dist\PlugClient.dll`.
- [ ] Generate SHA-256 hashes and a deployment manifest.
- [ ] Do not copy the DLL into the production generator or client in this phase.
- [ ] Document the exact reversible deployment steps for a later approved runtime smoke test.

## Completion Gate

- [ ] Delphi plugin compiles successfully.
- [ ] Static scan finds no UI setters, event setters, game commands, or gameplay logic.
- [ ] Node tests pass.
- [ ] DLL and deployment manifest exist only inside `XY_UI_Toolkit`.
