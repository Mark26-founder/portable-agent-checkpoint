# PAC S9 Benchmark — Evidence & Empirical Validation

## Classification

**PILOT BENCHMARK** — 3 tasks, protocol-level simulation.
Not a live multi-agent execution. Results are clearly labeled by evidence quality throughout.

---

## 1. Hypothesis

> A receiving agent given a PAC checkpoint (`pac resume` output) will reach its first
> productive implementation action in fewer steps and with less reconstruction work
> than a receiving agent given only the repository and original objective.

---

## 2. Benchmark Questions

1. Does PAC reduce reconstruction steps before first productive action?
2. Does PAC surface non-obvious architectural decisions that are invisible in code alone?
3. Does the `pac resume` output fit under 1,000 tokens (context budget)?
4. Is the stopping point unambiguous from the resume output?

---

## 3. Task Definitions

Three controlled benchmark tasks were designed. Each task represents a realistic
mid-implementation stopping point with meaningful reconstruction cost.

| Task | ID | Objective |
|---|---|---|
| Rate Limiting Middleware | `T1-rate-limiter` | Add per-user sliding-window rate limiting to a REST API |
| CSV Export Feature | `T2-csv-export` | Add a streaming CSV export endpoint to the reporting module |
| JWT Token Refresh | `T3-token-refresh` | Implement refresh token rotation for JWT auth |

### Task design criteria (all three tasks satisfy):
- ≥ 2 files touched by Agent A
- ≥ 2 architectural decisions embedded in comments (not in config or schema)
- ≥ 3 reconstruction signals (context that Agent B cannot recover without reading files)
- Clear stopping point mid-implementation (not at a clean commit boundary)
- At least one deliberate constraint not visible from code structure alone

### Example reconstruction signals (T1):
- Thread-safety decision is in a code comment inside the class docstring
- Redis exclusion constraint is not in any requirements or config file
- JSON error body format is a TODO comment only
- "authenticated routes only" scope is a comment in app.py

---

## 4. Baseline Condition

Agent B receives:
- Repository files at Agent A's stopping point
- Original task objective

Agent B must reconstruct:
1. What files Agent A created/modified → read each file
2. What architectural decisions were made → analyze code comments
3. Where exactly Agent A stopped → find TODOs / NotImplementedErrors
4. What constraints exist → read every comment mentioning constraints
5. What the next action is → infer from stopping point

**No PAC checkpoint. No structured work state.**

---

## 5. PAC Condition

Agent B receives:
- Repository files at Agent A's stopping point
- Original task objective
- `pac resume` output (structured work state)

Agent B actions:
1. Read `pac resume` output (1 action)
2. Spot-check one key file to confirm understanding (1 action)
3. Execute correct first productive action immediately

**Resume output is under 1,000 tokens for all tasks.**

---

## 6. Controlled Variables

| Variable | Controlled? | Notes |
|---|---|---|
| Repository state | ✅ Yes | Same workspace for both conditions |
| Original objective | ✅ Yes | Identical text |
| Stopping point | ✅ Yes | Agent A stopped at identical point |
| Evaluation criteria | ✅ Yes | Same action taxonomy |
| Agent model | ⚠️ Protocol-level | No live LLM; actions are simulated |
| Timing | ⚠️ N/A | Protocol-level; wall-clock time not measured |
| Agent reasoning variation | ⚠️ N/A | Simulation uses deterministic action sequences |

**Uncontrolled variables are explicitly documented above.**

---

## 7. Measurement Definitions

### Productive action
The first meaningful action that advances the unfinished task based on actual preserved state.

Examples that **count**:
- Editing the specific incomplete file identified in the checkpoint
- Running the correct next test
- Creating the next missing file explicitly documented as remaining

Examples that **do NOT count**:
- Listing files to discover project structure
- Reading already-complete files to understand what was done
- Asking what the previous agent did
- Re-implementing completed work

### Action taxonomy

| Class | Definition |
|---|---|
| `RECONSTRUCTION` | Action spent recovering already-known context |
| `PRODUCTIVE` | Action that advances unfinished implementation |
| `DUPLICATE` | Action that repeats Agent A's completed work |
| `ERROR` | Action taken on incorrect assumption |

### Token estimate
Conservative proxy: `len(resume_text) // 4` (GPT-style character-to-token ratio).
Actual model tokenization may differ.

---

## 8. Experimental Procedure

For each task:

1. Write Agent A's files to a clean temporary workspace
2. Call `_capture_pac_checkpoint()` to produce `.ai/checkpoint.json`
3. Call `format_resume_output()` to produce `pac resume` text
4. Run `_simulate_baseline()`: generate deterministic action sequence for baseline condition
5. Run `_simulate_pac()`: generate deterministic action sequence for PAC condition
6. Collect `ConditionResult` objects
7. Compute `TaskResult` (reduction metrics)

The harness is in `src/pac/benchmark/runner.py`.
Tasks are defined in `src/pac/benchmark/tasks.py`.

---

## 9. Raw Results

### T1 — Rate Limiting Middleware

| Metric | Baseline | PAC | Delta |
|---|---|---|---|
| Total actions | 10 | 3 | −7 |
| Reconstruction actions | 9 | 2 | **−7** |
| Productive actions | 1 | 1 | — |
| Steps before first productive | 9 | 2 | **−7** |
| Resume output lines | — | 52 | — |
| Resume tokens (est.) | — | 676 | — |
| Reconstruction reduction | — | — | **80%** |

**Baseline action sequence:**
1. `RECONSTRUCTION` Read src/middleware/__init__.py
2. `RECONSTRUCTION` Read src/middleware/rate_limiter.py
3. `RECONSTRUCTION` Read tests/test_rate_limiter.py
4. `RECONSTRUCTION` Analyze: NotImplementedError stopping point
5. `RECONSTRUCTION` Analyze: thread-safety decision in code comment
6. `RECONSTRUCTION` Analyze: Redis constraint (no config file)
7. `RECONSTRUCTION` Analyze: JSON body format in TODO comment
8. `RECONSTRUCTION` Analyze: "authenticated routes only" scope
9. `RECONSTRUCTION` Determine exact stopping point
10. `PRODUCTIVE` Edit rate_limiter.py — implement 429 response body

**PAC action sequence:**
1. `RECONSTRUCTION` Read pac resume output
2. `RECONSTRUCTION` Spot-check src/middleware/__init__.py
3. `PRODUCTIVE` Edit rate_limiter.py — implement 429 response body

---

### T2 — CSV Export Feature

| Metric | Baseline | PAC | Delta |
|---|---|---|---|
| Total actions | 10 | 3 | −7 |
| Reconstruction actions | 9 | 2 | **−7** |
| Productive actions | 1 | 1 | — |
| Steps before first productive | 9 | 2 | **−7** |
| Resume output lines | — | 51 | — |
| Resume tokens (est.) | — | 605 | — |
| Reconstruction reduction | — | — | **77.8%** |

**Baseline action sequence:**
1. `RECONSTRUCTION` Read src/reports/__init__.py
2. `RECONSTRUCTION` Read src/reports/exporter.py
3. `RECONSTRUCTION` Read tests/test_exporter.py
4. `RECONSTRUCTION` Analyze: column order contract in comment
5. `RECONSTRUCTION` Analyze: QUOTE_ALL requirement in comment
6. `RECONSTRUCTION` Analyze: streaming vs non-streaming split
7. `RECONSTRUCTION` Analyze: no HTTP endpoint file exists yet
8. `RECONSTRUCTION` Analyze: no-pandas constraint not in requirements
9. `RECONSTRUCTION` Determine exact stopping point
10. `PRODUCTIVE` Edit exporter.py — complete generate_csv_streaming()

**PAC action sequence:**
1. `RECONSTRUCTION` Read pac resume output
2. `RECONSTRUCTION` Spot-check src/reports/__init__.py
3. `PRODUCTIVE` Edit exporter.py — complete generate_csv_streaming()

---

### T3 — JWT Token Refresh

| Metric | Baseline | PAC | Delta |
|---|---|---|---|
| Total actions | 10 | 3 | −7 |
| Reconstruction actions | 9 | 2 | **−7** |
| Productive actions | 1 | 1 | — |
| Steps before first productive | 9 | 2 | **−7** |
| Resume output lines | — | 52 | — |
| Resume tokens (est.) | — | 717 | — |
| Reconstruction reduction | — | — | **77.8%** |

**Baseline action sequence:**
1. `RECONSTRUCTION` Read src/auth/__init__.py
2. `RECONSTRUCTION` Read src/auth/tokens.py
3. `RECONSTRUCTION` Read tests/test_tokens.py
4. `RECONSTRUCTION` Analyze: HS256 vs RS256 decision in comment
5. `RECONSTRUCTION` Analyze: one-time-use enforcement in comments and tests
6. `RECONSTRUCTION` Analyze: TODO for /auth/refresh (no routes.py exists)
7. `RECONSTRUCTION` Analyze: 401 vs 400 distinction in comment
8. `RECONSTRUCTION` Analyze: persistence requirement warning
9. `RECONSTRUCTION` Determine exact stopping point
10. `PRODUCTIVE` Create src/auth/routes.py with POST /auth/refresh handler

**PAC action sequence:**
1. `RECONSTRUCTION` Read pac resume output
2. `RECONSTRUCTION` Spot-check src/auth/__init__.py
3. `PRODUCTIVE` Create src/auth/routes.py with POST /auth/refresh handler

---

## 10. Aggregated Results

| Metric | Baseline Total | PAC Total | Delta |
|---|---|---|---|
| Total reconstruction steps | 27 | 6 | **−21** |
| Total steps before first productive | 27 | 6 | **−21** |
| Aggregate reconstruction reduction | — | — | **77.8%** |
| Resume token budget (all tasks) | — | 676 / 605 / 717 | All < 1,000 ✅ |

---

## 11. Evidence Classification & Interpretation

**Evidence quality classification** (per PAC evidence model):

| Finding | Classification | Details |
|---|---|---|
| Baseline condition required 9 modeled reconstruction steps per task | `OBSERVED` | Counted from benchmark harness simulation trace |
| PAC condition required 2 modeled reconstruction steps per task | `OBSERVED` | Counted from benchmark harness simulation trace |
| PAC reduced modeled reconstruction steps by 77.8% in this simulation | `CALCULATED` | (27 baseline − 6 PAC) / 27 total baseline steps |
| `pac resume` output fits under 1,000 approximate tokens | `OBSERVED` | Approximate token estimates based on character/token proxy (676, 605, 717) |
| PAC surfaces non-code architectural decisions (HS256 choice, Redis exclusion, thread-safety) | `OBSERVED` | Confirmed in resume prompt text |
| PAC's preserved work-state representation can reduce reconstruction burden | `INFERRED` | Suggested by controlled protocol under modeled conditions |
| Results generalize to real LLM agents, large repositories, or models | `UNKNOWN` | Not established by this protocol-level benchmark |
| Real token usage decreases by the estimated amount or wall-clock time improves | `UNKNOWN` | Requires live-agent empirical validation |

### Main Finding

In this controlled protocol-level simulation, the PAC condition required 2 modeled reconstruction steps versus 9 for the baseline (77.8% calculated reduction).

The protocol-level benchmark provides preliminary evidence that PAC's preserved work-state representation can reduce modeled reconstruction burden. Validation with live AI agents remains an open question.

---

## 12. Token Estimate Language

The resume token figures reported (676, 605, 717 tokens) are approximate token estimates based on the benchmark's character/token proxy (`len(text) // 4`). 

These figures demonstrate that the resume output fits well within a compact prompt budget, but they do not represent actual token consumption or claim actual API token savings under live model APIs.

---

## 13. Product Implication

Protocol-level result:
- PAC condition: 2 modeled reconstruction steps
- Baseline condition: 9 modeled reconstruction steps
- Calculated reduction: 77.8%

Interpretation:
The controlled protocol indicates that PAC's preserved work-state representation can substantially reduce modeled reconstruction effort.

Validation limitation:
No live LLM independently performed the reconstruction actions in this benchmark.

Open question:
Whether real coding agents exhibit a comparable reduction remains unvalidated.

---

## 14. Limitations

1. **Protocol-level simulation** — No live LLM independently performed the reconstruction actions in this benchmark. Actions are determined by rule-based simulation. A real agent might require more or fewer steps, misinterpret work-state context, or skip steps.

2. **Small sample** — 3 tasks is a pilot, not a statistically significant study. Results may not generalize.

3. **Action count as proxy** — Counting modeled reconstruction steps is a transparent proxy metric, not a direct measurement of real AI agent behavior, developer time, or actual API token consumption.

4. **Optimistic PAC condition** — The PAC simulation assumes the resume output is immediately understood. A real agent might misread or need clarification.

5. **Conservative baseline** — The baseline simulation assumes an agent that must read every file. A skilled agent might use directory listing + targeted reads to skip some reconstruction steps.

6. **Approximate token estimates** — The 4-char/token estimate is a rough character/token proxy. Actual tokenization depends on the model.

7. **No timing data** — Wall-clock time was not measured (protocol-level benchmark).

---

## 15. Future Experiment Ideas

1. **Live LLM execution** — Run both conditions using an actual Claude/GPT-4/Gemini agent and record real tool call sequences.

2. **Larger task corpus** — Run 10–20 diverse tasks across different domains and team sizes.

3. **Decision accuracy measurement** — After Agent B acts, compare its architectural decisions against Agent A's original decisions to measure context fidelity.

4. **Token counting** — Use actual model tokenization APIs to measure input token counts precisely.

5. **Multi-session PAC** — Benchmark tasks where Agent A worked across multiple sessions (multiple checkpoints), testing history and recovery features.

6. **Negative case** — Benchmark tasks where the PAC checkpoint is stale, testing whether PAC's staleness detection prevents wrong-direction work.

---

## 16. Reproducibility

The benchmark is fully reproducible:

```bash
py -3 -c "
from pac.benchmark.runner import run_benchmark, format_results_report
from pac.benchmark.tasks import ALL_TASKS
results = run_benchmark(ALL_TASKS)
print(format_results_report(results))
"
```

All task definitions and simulation logic are in:
- `src/pac/benchmark/tasks.py`
- `src/pac/benchmark/runner.py`
