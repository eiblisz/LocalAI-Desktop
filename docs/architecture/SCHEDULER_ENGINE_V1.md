# Scheduler Engine and Windows Background Runner V1

## Purpose

LocalAI Desktop originally executed recurring tasks only from the GUI process through
a Qt timer. That remains a supported compatibility path, but it is no longer the only
execution authority.

V1 adds a shared scheduler engine and a Windows background runner so recurring tasks can
continue while the Desktop window is closed.

## Runtime boundaries

### Desktop

The Desktop remains the control plane:

- create/edit/delete schedules;
- Run Now;
- display task health;
- display scheduled chats and results.

The Desktop may still execute a due task while it is open.

### ScheduledTaskStore

The store is the execution-authority boundary.

Before execution, a process must claim a task. A claim records:

- `lease_owner`
- `lease_until`
- `attempt_id`
- `attempt_started_at`
- `attempt_count`

Only the process holding the current attempt may persist the result.

An expired lease may be recovered by a new process. The previous stale attempt cannot
later overwrite the newer result.

Writes are protected with a cross-process lock and atomic file replacement.

### ScheduledTaskExecutor

`app/scheduled_task_executor.py` is the canonical task execution implementation used by
both the Desktop worker and the background engine.

Supported task types remain unchanged:

- weather;
- eBay;
- computer status;
- custom;
- optional bounded web search for custom tasks.

### SchedulerEngine

`app/scheduler_engine.py` performs one bounded cycle:

1. claim the next due task;
2. execute it with the canonical executor;
3. save the result to the dedicated `[SCHEDULE]` chat;
4. persist success/failure;
5. release the lease.

### Background runner

`python -m app.scheduler_runner --loop --interval 30`

runs the engine without opening the Desktop GUI.

The runner log is stored under the LocalAI private runtime schedules directory as
`runner.log`.

## Windows registration

The repository includes:

- `scripts/register_scheduler_runner.ps1`
- `scripts/unregister_scheduler_runner.ps1`

The registration script creates a current-user Windows Scheduled Task that starts the
runner at logon, keeps one instance, removes the normal execution-time limit, and asks
Task Scheduler to restart the process after failures.

The runner uses `.venv\Scripts\pythonw.exe`, so it does not keep a console window open.

This V1 is intentionally a current-user background runner, not a Windows Service. It
runs after that Windows user logs in. A pre-login machine service would be a separate,
privileged deployment mode.

## Duplicate-execution safety

The Desktop and background runner may both observe the same due schedule. They do not
both execute it: the first successful atomic claim owns that attempt.

Run Now also obtains a lease. If another process already owns the task, the Desktop
reports that the run was skipped because another LocalAI scheduler process is running it.

## Crash recovery

The default lease is one hour. If a process crashes without recording success/failure,
the lease eventually expires and a new runner may reclaim the task.

Each reclaim receives a new `attempt_id`. A late callback from the old attempt is
rejected as stale.

## Acceptance

V1 is accepted when:

- existing Desktop Run Now behavior still works;
- existing recurring Desktop execution still works;
- a headless runner can execute a due task and save its scheduled chat;
- simultaneous Desktop/runner observation results in one claim only;
- an expired lease can be reclaimed;
- a stale attempt cannot overwrite a newer result;
- Windows registration/unregistration scripts are present;
- exact-head GitHub CI passes.
