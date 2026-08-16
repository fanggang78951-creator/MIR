# XY UI Toolkit Phase 3 Resource Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a safe resource CLI for bitmap validation, source/client PAK comparison, and editor-assisted replacement transactions.

**Architecture:** Node.js reads image headers and file metadata directly but treats PAK/WZL payloads as private formats. It stages backups and manifests, then verifies editor-produced changes without rewriting or optimizing the package.

**Tech Stack:** Node.js 24 ESM and built-in tests.

## Tasks

1. Implement BMP/PNG header inspection with tests for dimensions, bit depth, compression, and malformed files.
2. Implement source/client PAK fingerprint comparison.
3. Extend transactions with metadata and stage a single-index editor-assisted replacement.
4. Add `xy-resource asset-info`, `compare`, `scan`, and `stage-replace` commands.
5. Run tests and a read-only production comparison against the confirmed source and client `NewopUI.Pak` files.

## Safety Gate

- Never open, create, rewrite, optimize, or truncate a PAK/WZL payload.
- `stage-replace` only creates backups and a transaction manifest inside the toolkit.
- Only 24-bit uncompressed BMP files are accepted for staged Wzl replacement.
- The only default source PAK path is beneath `D:\素材文件夹\全新聆风\LFM2[20260530]\登录器`.
