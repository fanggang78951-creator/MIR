# Nonresident Script v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe section/key TXT merging to the installer and deliver optional, configuration-driven rage and donation core packages with separate NPC and command trigger packages.

**Architecture:** A focused `configpatch.py` module parses INI-like LFM2 TXT files, rejects duplicate sections/keys, preserves existing values, and adds only missing defaults. The installer exposes this as a declarative `config_merge` operation. Each nonresident feature is split into a core package plus optional entry adapters; runtime state is written only by game scripts under `玄渊数据`, never by package installation.

**Tech Stack:** Python 3.12, `unittest`, Tkinter platform core, UTF-8 package payloads, GB18030 LFM2 target scripts, JSON manifests.

---

### Task 1: Implement the configuration merge primitive

**Files:**
- Create: `D:\XuanYuanDevPlatform\src\xydp\configpatch.py`
- Create: `D:\XuanYuanDevPlatform\tests\test_config_merge_operation.py`

- [ ] **Step 1: Write failing parser and merge tests**

Create tests for: absent target creates template; existing values remain unchanged; missing keys and sections are appended; duplicate section and duplicate key raise `ConfigPatchError`; CRLF and GB18030 round-trip through installer helpers.

```python
def test_existing_values_are_preserved_and_missing_defaults_are_added(self):
    current = "[消耗]\r\n消耗数量=999\r\n"
    defaults = "[消耗]\n消耗类型=账户金刚石\n消耗数量=100\n[属性]\n神力倍攻=200\n"
    merged = merge_config_text(current, defaults, "\r\n")
    self.assertIn("消耗数量=999", merged)
    self.assertIn("消耗类型=账户金刚石", merged)
    self.assertIn("[属性]\r\n神力倍攻=200", merged)
    self.assertNotIn("消耗数量=100", merged)
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m unittest tests.test_config_merge_operation -v`  
Expected: FAIL because `xydp.configpatch` does not exist.

- [ ] **Step 3: Implement strict parsing and additive merge**

Define:

```python
class ConfigPatchError(RuntimeError):
    pass

def merge_config_text(current: str | None, defaults: str, newline: str) -> str:
    """Return defaults for a missing file; otherwise preserve every existing value and append only absent sections/keys."""
```

Parsing rules: `[节]` starts a unique section; each nonblank non-comment line inside a section must contain `=`; keys are unique case-insensitively within a section; duplicate sections/keys and keys before the first section raise `ConfigPatchError`; comments and existing line order remain untouched.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_config_merge_operation -v`  
Expected: all primitive tests PASS.

### Task 2: Add `config_merge` to package validation and installation

**Files:**
- Modify: `D:\XuanYuanDevPlatform\src\xydp\validator.py`
- Modify: `D:\XuanYuanDevPlatform\src\xydp\installer.py`
- Modify: `D:\XuanYuanDevPlatform\tests\test_config_merge_operation.py`

- [ ] **Step 1: Write failing operation tests**

Add an isolated package using:

```json
{
  "type": "config_merge",
  "source": "payload/demo-config.txt",
  "target": "Mir200/Envir/QuestDiary/玄渊配置/演示配置.txt",
  "source_encoding": "utf-8",
  "target_encoding": "gb18030"
}
```

Assert preflight is read-only, install preserves an existing custom value and adds a missing key, second preflight is a no-op, rollback restores the original bytes, and validator rejects a missing source.

- [ ] **Step 2: Run focused tests and verify unsupported-operation failure**

Run: `python -m unittest tests.test_config_merge_operation -v`  
Expected: FAIL with `不支持的操作类型: config_merge`.

- [ ] **Step 3: Implement operation validation and application**

Add `config_merge` to `ALLOWED_OPERATIONS`, validate its source like `render`, then in `Installer._apply_operation` decode the existing target with `read_text_document`, read the UTF-8 defaults, call `merge_config_text`, and encode with the existing target encoding/newline or the declared target defaults when absent.

```python
if op_type == "config_merge":
    defaults = source.read_text(encoding=operation.get("source_encoding", "utf-8"))
    document = existing_document_or_declared_default
    merged = merge_config_text(document.text if before is not None else None, defaults, document.newline)
    return encode_text_document(document, merged)
```

- [ ] **Step 4: Run focused and transaction tests**

Run: `python -m unittest tests.test_config_merge_operation tests.test_planner_transaction -v`  
Expected: all tests PASS.

### Task 3: Create rage v2 core and optional trigger packages

**Files:**
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.rage.core\manifest.json`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.rage.core\payload\狂暴核心.txt`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.rage.core\payload\狂暴配置.txt`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.rage.npc\manifest.json`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.rage.npc\payload\狂暴入口.txt`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.rage.command\manifest.json`
- Create: `D:\XuanYuanDevPlatform\tests\test_nonresident_v2_packages.py`

- [ ] **Step 1: Write failing rage package contract tests**

Assert all three packages are candidate/optional; core has no `unique_line` and no `MerChant`; NPC and command packages depend on core; all adapters call `@XY_RAGE_TRIGGER`; every business key appears in `狂暴配置.txt`; core uses `ReadConfigFileItem`; core contains no literal `GAMEDIAMOND - 100` or `POWERRATE 200`.

- [ ] **Step 2: Run focused test and verify missing-package failure**

Run: `python -m unittest tests.test_nonresident_v2_packages.NonresidentV2PackageTests.test_rage_packages -v`  
Expected: FAIL because v2 packages do not exist.

- [ ] **Step 3: Implement rage core package**

Core installs `狂暴核心.txt`, additively installs `狂暴配置.txt`, ensures/hooks required shared events, and exposes stable label `@XY_RAGE_TRIGGER`. It reads feature enable, cost type/name/count, power and lifecycle values at runtime. Currency/material branches use the read variables; death/offline handlers clear the status according to configured switches. No NPC or database operation appears in core.

- [ ] **Step 4: Implement NPC and command adapters**

NPC parameters are map, x, y, display name, appearance and script path; its payload contains only dialogue and `#CALL [\玄渊功能\狂暴\狂暴核心.txt] @XY_RAGE_TRIGGER`. Command adapter adds only a managed command/event entry that calls the same label.

- [ ] **Step 5: Validate and test rage packages**

Run: `python -m xydp.cli --root D:\XuanYuanDevPlatform validate-package <package-path>` for all three packages, then `python -m unittest tests.test_nonresident_v2_packages -v`.  
Expected: package validation and rage tests PASS.

### Task 4: Create donation v2 core and optional trigger packages

**Files:**
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.donate.core\manifest.json`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.donate.core\payload\捐献核心.txt`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.donate.core\payload\捐献配置.txt`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.donate.npc\manifest.json`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.donate.npc\payload\捐献入口.txt`
- Create: `D:\XuanYuanDevPlatform\packages\candidate\xy.optional.donate.command\manifest.json`
- Modify: `D:\XuanYuanDevPlatform\tests\test_nonresident_v2_packages.py`

- [ ] **Step 1: Write failing donation contract tests**

Assert core has no NPC/database operation, adapters depend on core and call `@XY_DONATE_TRIGGER`, configuration includes cost, contribution increment, seal threshold, ranking and messages, core reads config at runtime, and runtime state paths are only under `玄渊数据/xy_donate`.

- [ ] **Step 2: Run focused test and verify missing-package failure**

Run: `python -m unittest tests.test_nonresident_v2_packages.NonresidentV2PackageTests.test_donate_packages -v`  
Expected: FAIL because donation v2 packages do not exist.

- [ ] **Step 3: Implement donation core package**

Core exposes `@XY_DONATE_TRIGGER`, reads cost/reward/ranking/seal values from `玄渊配置/沙城捐献配置.txt`, and uses `ReadConfigFileItem`/`WriteConfigFileItem` under `玄渊数据/xy_donate` for personal total, global total, leader and seal state. Installation never creates or overwrites runtime state files.

- [ ] **Step 4: Implement NPC and command adapters**

Both adapters only call the same public label. NPC map, coordinates, appearance, display name and script path remain installation parameters.

- [ ] **Step 5: Validate and test donation packages**

Run package validation for all three packages and `python -m unittest tests.test_nonresident_v2_packages -v`.  
Expected: all v2 package tests PASS.

### Task 5: Update platform documentation and retire conflicting guidance

**Files:**
- Modify: `D:\XuanYuanDevPlatform\knowledge\成果包开发规范.md`
- Modify: `D:\XuanYuanDevPlatform\knowledge\常驻与非常驻脚本使用说明.md`
- Modify: `D:\XuanYuanDevPlatform\knowledge\非常驻脚本制作规范.md`
- Modify: `D:\XuanYuanDevPlatform\README.md`

- [ ] **Step 1: Add `config_merge` documentation**

Document create-if-missing, preserve-existing, add-missing-only, duplicate rejection, encoding behavior and rollback behavior.

- [ ] **Step 2: Correct residency guidance**

Remove the historical statement that rage/donation may later become resident. State that all nonresident packages remain optional, including verified versions.

- [ ] **Step 3: Mark v2 implementation status accurately**

Replace “尚待实现” wording only after operation and package tests pass; list the six v2 candidate package IDs and retain the independent-server game-validation requirement.

- [ ] **Step 4: Scan for contradictions**

Run: `rg -n "狂暴.*常驻|捐献.*常驻|尚待实现|config_merge" D:\XuanYuanDevPlatform\knowledge D:\XuanYuanDevPlatform\README.md`  
Expected: no active guidance promotes rage/donation to resident; `config_merge` and remaining validation boundary are documented.

### Task 6: Full verification, frozen binaries and handoff

**Files:**
- Modify: `D:\XuanYuanDevPlatform\bin\XuanYuanDevPlatform.exe`
- Modify: `D:\XuanYuanDevPlatform\bin\xydp-cli.exe`
- Create: `D:\codex交班记录\20260713_1900_实现非常驻脚本包v2.txt`
- Modify: `D:\codex交班记录\00_任务总结索引.txt`
- Modify: `D:\codex交班记录\01_最近任务指针.txt`

- [ ] **Step 1: Run all platform and equipment tests**

Run: `python -m unittest discover -s tests -v` with platform `PYTHONPATH`, followed by equipment tests with both source roots.  
Expected: all tests PASS.

- [ ] **Step 2: Validate every package**

Run validation over every directory under `packages\verified` and `packages\candidate`.  
Expected: zero invalid manifests.

- [ ] **Step 3: Run an isolated install/rollback acceptance**

Create a temporary LFM2 fixture, install rage/donation core only and assert no NPC/MerChant/client changes; modify config values, preflight again and assert values remain; install adapters; rollback and compare original business files byte-for-byte.

- [ ] **Step 4: Build frozen GUI and CLI**

Run: `powershell -ExecutionPolicy Bypass -File D:\XuanYuanDevPlatform\build.ps1`  
Expected: tests run successfully and exactly two current executables remain in `bin`.

- [ ] **Step 5: Write handoff records**

Record backup path, changed files, test counts, package validation, executable hashes, no-write confirmation for `D:\MirServer`, and status `待验证` because M2/game validation has not yet occurred.
