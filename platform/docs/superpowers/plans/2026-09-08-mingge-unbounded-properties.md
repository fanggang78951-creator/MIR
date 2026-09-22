# Mingge Unbounded Properties Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the workbook-wide 11-property blocker without truncating real effects, preserve retired test candidates, and keep only safety-critical preflight blockers.

**Architecture:** Keep stable candidate IDs in instance rows 9-16. Compile candidate properties into runtime aggregates wherever a verified reset/apply outlet exists; reserve rows 1-8 and 17-19 only for properties that truly require native item records. Preserve retired candidates in the provider and TextVar mapping while excluding them from draw pools.

**Tech Stack:** Python 3.12, openpyxl, unittest, LFM2 GB18030/CRLF scripts, PyInstaller release pipeline.

**Spec:** `E:\XuanYuanDevPlatform\docs\superpowers\specs\2026-09-08-mingge-unbounded-properties-design.md`

## Global Constraints

- Modify only `E:\XuanYuanDevPlatform`; `D:\MirServer` is read-only during platform development.
- Do not write databases, client resources, or operate GameCenter/M2/login tools.
- Never truncate properties beyond row capacity and never convert a real property to display-only.
- Keep path, collision, hash-drift, managed-block, missing-real-outlet, encoding, install, and rollback protections.
- E drive is not a Git repository; use backups, file hashes, red/green test logs, and release evidence instead of commits.

---

### Task 1: Candidate active/retired/disabled states

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\mingge_dual.py`
- Test: `E:\XuanYuanDevPlatform\tests\test_mingge_dual.py`

**Interfaces:**
- Produces: `MinggeCandidate.state: str`, active draw candidates, retained provider candidates.

- [ ] **Step 1: Write failing tests**

Add tests proving `是`, `退役`, and `否` parse distinctly; retired candidates remain in `; CANDIDATE <ID> TEXTVAR <LINE>` and recalc branches but do not appear in `@XY_MG_CONTENT_POOL_*`; disabled drafts appear nowhere.

- [ ] **Step 2: Verify RED**

Run:
`python -m unittest tests.test_mingge_dual.MinggeDualTests.test_retired_candidate_keeps_identity_but_leaves_draw_pool -v`

Expected: FAIL because the existing boolean parser rejects `退役`.

- [ ] **Step 3: Implement minimal state parsing**

Introduce a parser that maps `是 -> active`, `退役 -> retired`, `否 -> disabled`. Load active and retired candidates into the content catalog; generate draw groups from active candidates only. Keep the existing stable-ID/TextVar mapping for both active and retired candidates.

- [ ] **Step 4: Verify GREEN and regressions**

Run the new test and the complete `tests.test_mingge_dual` module.

- [ ] **Step 5: Record checkpoint**

Write changed-file SHA256 values and test output to the task evidence directory; do not commit because the platform root has no `.git`.

### Task 2: Replace workbook-wide aggregation capacity with execution plans

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\mingge_dual.py`
- Test: `E:\XuanYuanDevPlatform\tests\test_mingge_dual.py`

**Interfaces:**
- Produces: `_content_execution_plan(book)` containing `runtime` and `native` property specifications.
- Consumes: existing `_property_spec`, `_runtime_attributes`, `_RUNTIME_VARIABLES`, `_SCRIPT_RUNTIME_VARIABLES`.

- [ ] **Step 1: Write failing 12/28-property tests**

Build synthetic content workbooks containing 12 and 28 distinct registered real-effect properties. Assert that rendering does not raise the old workbook-union error and that every property is present in either runtime or native plan.

- [ ] **Step 2: Verify RED**

Run the two tests. Expected: FAIL with `当前装备实例最多承载11种聚合实效属性`.

- [ ] **Step 3: Implement execution-plan classification**

Replace `_content_aggregates` with a classifier. Route all existing textline runtime properties and script bindings with verified unified variables to runtime. Route direct/script properties only when an explicit reset/apply adapter exists; otherwise retain them as native records or report the exact unsupported property.

- [ ] **Step 4: Generate runtime aggregation by candidate ID**

For every runtime plan entry, emit a zero, eight-slot candidate-ID accumulation, and one unified apply call. Do not write these properties into rows 1-8 or 17-19.

- [ ] **Step 5: Generate dynamic native records**

Clear only the 11 package-owned native rows and rebuild records needed by the currently selected candidate IDs. If a reachable current instance needs more than 11 native-only property types, stop with their names; never use `zip` truncation.

- [ ] **Step 6: Verify GREEN**

Assert 12/28-property plans have no omissions, no database commands, one continuous instance lock/update chain, and no second `ChangeSpeed 2`.

- [ ] **Step 7: Record checkpoint**

Save test output and changed-file hashes in the task evidence directory.

### Task 3: Audit and narrow content-route blockers

**Files:**
- Modify: `E:\XuanYuanDevPlatform\src\xydp\mingge_dual.py`
- Test: `E:\XuanYuanDevPlatform\tests\test_mingge_dual.py`

**Interfaces:**
- Produces: warnings with GB18030 byte lengths; blockers only for concrete safety or unsupported real effects.

- [ ] **Step 1: Write failing text-length test**

Create a valid candidate whose rendered text exceeds 128 Python characters but serializes successfully. Assert preflight returns a warning containing its GB18030 byte count instead of a blocker.

- [ ] **Step 2: Verify RED**

Expected: FAIL with `原生多色文本超过引擎128字符上限`.

- [ ] **Step 3: Replace the unverified hard limit**

Remove the `len(rendered) > 128` blocker. Compute `len(rendered.encode("gb18030"))` and add a warning plus preview. Encoding failure remains a blocker.

- [ ] **Step 4: Add blocker classification regression tests**

Keep tests for static-only properties, TextVar collisions, attack-speed dependency, managed-block conflicts, target/path errors, input/target drift, and rollback integrity. Assert no candidate-count or workbook-property-count blocker remains.

- [ ] **Step 5: Verify GREEN**

Run the full content-route module and inspect raw blocker/warning output.

### Task 4: Documentation, manifests, regression, and frozen release

**Files:**
- Modify: `E:\XuanYuanDevPlatform\接口\45_命格内容与多色属性双包接口.txt`
- Modify: `E:\XuanYuanDevPlatform\packages\candidate\xy.optional.mingge-content\manifest.json`
- Modify: `E:\XuanYuanDevPlatform\所需材料表格汇总\41_命格内容与多色属性.xlsx`（仅扩展“启用”列的数据验证和中文说明以支持“退役”）
- Modify: platform feature annotation/current-version records required by release workflow.

**Interfaces:**
- Documents three-state candidates, runtime/native execution plan, retained blockers, warnings, rollback, and game-validation boundary.

- [ ] **Step 1: Update Chinese contract**

Replace the obsolete 11-property workbook limit with runtime/native routing behavior. Document `是/退役/否`, old-ID preservation, and byte-length warnings.

- [ ] **Step 2: Update package metadata**

Remove `property-row-capacity` from preflight checks and add `real-effect-route`, `retired-id-preservation`, and `native-instance-capacity`.

- [ ] **Step 3: Verify workbook compatibility**

If the existing “启用” validation rejects `退役`, extend only that validation/list and its Chinese explanation. Preserve every existing business row and style; render and visually inspect each affected sheet.

- [ ] **Step 4: Run regressions**

Run `tests.test_mingge_dual`, all Mingge modules, platform full unittest discovery, and `做装备` full unittest discovery.

- [ ] **Step 5: Build frozen GUI/CLI**

Run `build.ps1` with a unique release ID. Verify GUI/CLI provenance, current release pointer, frozen CLI preflight, and artifact hashes.

- [ ] **Step 6: Read-only target verification**

Run frozen preflight against `D:\MirServer`; record blockers/changes without installation. Hash current server boundary files before and after to prove zero writes.

- [ ] **Step 7: Clean temporary files and hand off**

Delete task-specific temporary previews and development backups after verification, retain formal release evidence, and update the single task handoff/feature card with status `待验证`.
