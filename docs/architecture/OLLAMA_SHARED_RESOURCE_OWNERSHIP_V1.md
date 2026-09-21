# Ollama Shared Resource Ownership V1

Status: implementation contract.

## Purpose

Ollama is a shared system resource. LocalAI Desktop must not assume that every
loaded model, runner process, or GPU allocation belongs to the Desktop.

The same runtime may be used by LocalAI Desktop, EinsteinAI, the background
scheduler, a manual `ollama run`, or another local application.

The safety rule is:

> UNKNOWN ownership is not LocalAI Desktop ownership.

Destructive operations are fail-closed unless ownership is proven.

## Owners

Canonical owner types:

- `LOCALAI_DESKTOP`
- `EINSTEIN`
- `MANUAL`
- `SCHEDULER`
- `OTHER`
- `UNKNOWN`

## Lease states

Canonical states:

- `IDLE`
- `RESERVED`
- `MODEL_LOADING`
- `INFERENCE_ACTIVE`
- `RELEASING`
- `STALE`
- `ERROR`

The local lease ledger records owner, owner identity, model, owner PID,
model/runner PID when it can be proven, request identity, start time, last
heartbeat, state, and diagnostic detail.

The canonical ledger path is the LocalAI Desktop runtime root
(`%LOCALAPPDATA%\\LocalAI-Desktop\\ollama_resource_leases.json` on the
normal Windows installation). Cooperating local applications may point to a
shared alternate path with `LOCALAI_OLLAMA_RESOURCE_LEASE_PATH`.

## Model switching

Automatic model preparation first checks visible external Ollama clients before
trusting the resident-model list. This is required because a manual
`ollama run` session may exist even when `/api/ps` is temporarily empty or
transitional.

Automatic model preparation may gracefully unload a different loaded model only
when all of the following are true:

1. the loaded model has an exact lease for the current caller;
2. that lease is not in active inference;
3. runner discovery succeeds;
4. no conflicting external Ollama consumer is visible;
5. the external-consumer check still passes immediately before unload.

If ownership is foreign or unknown, LocalAI Desktop reports the shared runtime as
busy and does not unload or kill anything.

Automatic model switching never kills a runner and never restarts the Ollama
server.

## FREE VRAM

FREE VRAM is limited to gracefully unloading models with exact, idle
LocalAI Desktop ownership.

If a loaded model is owned by Einstein, the scheduler, a manual client, another
application, or has unknown ownership, FREE VRAM is blocked for that model.

## KILL MODEL PROCESS

KILL MODEL PROCESS requires an ownership-authorized runner PID recorded by the
current LocalAI Desktop lease. Global runner discovery is not kill authority.

If the PID cannot be tied to the current Desktop owner, the action is blocked.

## RESTART OLLAMA

RESTART OLLAMA is never part of normal model switching. It is an explicit user
action only.

The action is blocked when a known foreign active lease or external consumer is
present. Otherwise the user must confirm a warning that other local AI processes
may also be interrupted.

## EMERGENCY OLLAMA KILL

EMERGENCY OLLAMA KILL is a deliberately global action. It is available only as
an explicit user action with a warning:

`Mas helyi AI folyamatokat is megszakithat.`

It is not used by automatic recovery.

## Runtime reconciliation

A model may temporarily remain visible in Ollama state while its runner process
is already gone, for example a `Stopping...` display after GPU memory has been
released.

When the model is listed but no runner process exists, LocalAI Desktop marks the
lease STALE and treats the condition as reconciliation. It does not escalate to
a process kill.

## Scheduler

The background scheduler uses the same resource ledger with owner
`SCHEDULER`. It does not inherit LocalAI Desktop destructive authority merely
because both use the same Ollama server.

## Acceptance

The contract is accepted only if tests prove:

- unknown ownership blocks destructive model control;
- foreign active ownership blocks model switching;
- a visible manual `ollama run qwen...` blocks switching to a different model
  before resident-model state is consulted;
- own idle ownership permits graceful unload;
- active inference is not FREE VRAM authority;
- KILL MODEL PROCESS requires explicit authorized PIDs;
- automatic preparation contains no runner kill or server restart path;
- stale listed/no-runner state reconciles without killing;
- Desktop and scheduler use distinct owner identities;
- Qwen3-Coder 30B remains the preferred Desktop model.
