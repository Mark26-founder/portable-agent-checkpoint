# Product Specification: Portable Agent Checkpoint (PAC)

## Problem Definition
AI coding work is frequently trapped inside individual, ephemeral agent sessions. When a developer switches AI coding agents, hits session context limits, restarts an IDE, or hands off a repository to another developer, the receiving agent has zero structured awareness of the prior agent's work state.

To resume work, the new agent must reconstruct context from scratch by re-reading files, parsing raw conversation histories (if available), or re-running tests. This leads to redundant token consumption, high latency before productive action, duplicate work, and repeated mistakes.

## Target User
* Software developers using AI coding agents (e.g., Claude, Cursor, Antigravity, Codex, Copilot Workspace).
* Teams handing off active feature development between different AI agents or human developers.

## First Use Case
Software development tasks handed off between two AI coding agents (or session resets within the same agent framework).

## Product Definition
PAC (Portable Agent Checkpoint) is a local-first, open-source system that captures, verifies, compresses, and transfers the working state of an AI-assisted software development task between AI agents and humans.

Core Principle:
> **"Git preserves code state. PAC preserves AI work state."**

## Core Value Proposition
**Switch AI coding agents without losing your work state.**

## What PAC Is NOT (Non-Goals)
PAC is explicitly **NOT**:
* An AI coding agent
* An agent framework
* An IDE or IDE plugin
* A project-management system or task tracker
* An observability or tracing platform
* A vector database or RAG system
* A memory chatbot
* A SaaS platform or hosted backend
* A multi-agent orchestration framework

## Four MVP Operations
1. **`capture`**: Evaluates project git state and explicit agent-provided inputs (via structured input files, CLI flags, or adapters) to produce a structured `.ai/checkpoint.json` file.
2. **`verify`**: Evaluates checkpoint claims against actual local environment/repository evidence to detect staleness and invalid claims.
3. **`resume`**: Generates a hyper-compact, context-compressed Markdown continuation prompt for the receiving AI agent or developer.
4. **`diff`**: Computes and displays human/agent-readable work-state changes between two checkpoints.

## Success Conditions
1. **Fast Time-to-Productive-Action**: Receiving agent executes the correct next action immediately without redundant context searching.
2. **Strict Verification**: Claims (e.g. "tests pass") are never falsely presented as facts unless verified by tool output or environment inspection.
3. **Context Compression**: Resume prompt consumes <1,000 tokens while conveying complete task context.
4. **Zero-Lockin/Local-First**: Checkpoints are plain JSON files stored inside `.ai/` and commit-friendly.

## Killer Workflow
```text
AI Agent A (e.g. Cursor / Antigravity)
   └─ Works on feature, makes progress, hits limit / switches tool
   └─ Executes `pac capture` -> `.ai/checkpoint.json`
          │
          ▼
AI Agent B (e.g. Claude Code / Generic CLI Agent)
   └─ Executes `pac resume` (or developer injects resume output)
   └─ Continues implementation immediately without session reconstruction
```
