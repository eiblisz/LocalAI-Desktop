# LOCAL ORCHESTRATION BENCHMARK V1

## Purpose

This benchmark is the reproducible host-level acceptance gate for the LocalAI
Desktop orchestration safeguards. It is intentionally model-independent and
runs in Windows CI without Ollama.

It verifies the host/runtime responsibilities that must be correct before
attributing a failure to an individual local model.

## Covered acceptance cases

1. **Parent-task binding**
   - split subtasks inherit one canonical parent task;
   - Hungarian response-language constraints persist across every subtask.

2. **WEB AUTO / ON / OFF**
   - freshness-sensitive AUTO requests route to web;
   - ON forces web;
   - OFF forces LOCAL ONLY even for an explicit web-search phrase.

3. **Language/script guard**
   - accidental Hangul leakage is detected;
   - accidental CJK leakage is detected;
   - a clean Hungarian response is accepted.

4. **Context/entity drift**
   - stale Bitcoin -> Tesla subject substitution is detected;
   - legitimate referential follow-up is not blocked.

5. **Runtime budget**
   - a worker chain cannot exceed its bounded model-call budget.

## Running locally

From the repository root:

    .\.venv\Scripts\python.exe scripts\run_orchestration_benchmark.py

The command prints JSON and exits non-zero if any acceptance case fails.

## Model evaluation boundary

This host benchmark does not claim that a model is good or bad. A later live
model benchmark may compare direct Ollama output with Desktop-orchestrated output.
A model-level failure should only be diagnosed after these host-level cases pass.
