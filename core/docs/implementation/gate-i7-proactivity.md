# Gate I7 — Core proactivity implementation

Scope: SA-B021, SA-B022 and SA-B023 only. Baseline inspected before edits:
`c82e74a86428b5224c0a9d70fbcf249cb1ad6003`, clean `main`, aligned with
`origin/main`. Slice 07 is approved; I11 and the remainder of the Slice are not
implemented by this Gate. No Memory, UI, external watcher or general attention
policy has been added.

## Directed gap analysis and reference harvest

Existing Core lifecycle, SQLite/WAL migrations, TaskRuntime, ExecutionRuntime,
confirmation flow, authenticated Local Client Boundary, health models and SA-B030
Audit were inspected before implementation. The missing pieces were a local event
delivery owner, durable timing/occurrences, a WAITING_SCHEDULE continuation,
durable attention and an authenticated attention projection. Existing ownership,
Task claims, grants, Tool execution and Audit remain authoritative.

Accepted architecture constraints (especially ADR-0001 Core/client separation,
ADR-0002 persistence, ADR-0003 events/scheduling, ADR-0010 Task lifecycle and the
existing execution/Audit contracts) take precedence over
references. No architectural decision was reopened. In particular, a stored
continuation reenters ExecutionRuntime and Policy; event data cannot confer
capabilities. Client projections use the existing session authentication, not
SQLite access or a new trust boundary.

Directed references, used conceptually and clean-room:

- [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html): IANA rules,
  DST/fold and the need for `tzdata` on Windows. Used stdlib ZoneInfo, adding only
  the timezone-data dependency; no custom offset database.
- [Python asyncio event loop](https://docs.python.org/3/library/asyncio-eventloop.html):
  wakeups are process-local, not durable scheduling state. The worker periodically
  rereads the injected clock and database; it does not equate a timer with truth.
- [APScheduler user guide](https://apscheduler.readthedocs.io/en/master/userguide.html):
  persistent timing and coalescing are useful concepts. No scheduler framework,
  executor pool, distributed coordination or APScheduler dependency was imported.
- [Mark LI / current Mark-LIII repository](https://github.com/FatihMakes/Mark-LI)
  and [Brahma AI](https://github.com/SanjayGanesh614/Brahma-Ai): directed repository
  overview comparison found no reason to replace the existing Core seams. No code
  was copied, and no UI ownership, background agent authority, Memory dependency
  or broad agent framework was adopted.

## Ownership and persistence

`SofiaCore` owns `ProactivityRuntime`, composed of `EventBus`, `Scheduler` and
`NotificationService`. Startup recovers scheduled continuations, reconciles due
work and starts one bounded wakeup worker. Shutdown stops that worker and event
delivery before TaskRuntime and the Operational Store are closed. Optional
external sources have an explicit EventSource protocol and deterministic fake;
registering a source does not start hidden observation.

Incremental migration `0008_proactivity`, after `0007_audit_traceability`, adds:

| Table | Durable responsibility |
| --- | --- |
| `runtime_events` | Selective delivery outbox, identity, lease and handler progress |
| `schedules` | Timing intent, next occurrence, cancellation and continuation references |
| `notifications` | Pending/acknowledged attention independent of any client connection |

UUID identities, UTC timestamps, status/recurrence constraints, correlation and
due/pending indexes are explicit. Notifications have a unique event reference;
schedules reference existing Task/ToolCall records and their last emitted event.
Health transition deduplication uses existing ApplicationSetting records, not a
fourth new table. No Audit records are consumed as operational state. No event
history rebuilds Tasks, grants or schedules: this is not event sourcing.

Event payload/metadata are bounded string mappings (8 KiB each). Gate producers
write references/status only; reminder text stays in its user-intent record and
notification summary (1,024 characters). External adapters must normalize facts,
not put credentials, raw provider state, files or arbitrary blobs into events.
Audit contains IDs, outcomes and safe handler metadata, not these payloads, raw
exceptions or reminder text. Existing ToolCall persistence owns the deferred
call arguments, as for other Tool calls; they are not copied into event payloads.

## Event delivery semantics

- EPHEMERAL: publish dispatches a detached event to the current subscribers;
  no outbox, replay or retry guarantee. Shutdown cancels tracked transient work.
- DURABLE: publish commits the outbox first. Reusing an ID with different data is
  rejected; identical publication is idempotent. Only registered types are claimed.
- Claims use SQLite `BEGIN IMMEDIATE`, owner IDs and a five-minute lease. Each
  handler has at most five seconds and a type has at most 16 handlers. Each tick
  claims at most 100 events. Independent subscribers continue after a handler
  exception, and successful progress is retained per subscriber.
- Retry-safe handlers opt in explicitly. They receive at-least-once attempts,
  bounded to three ordinary failure attempts with 2/4-second backoff, then FAILED.
  Repeated process interruption can require additional recovery attempts. There
  is no exactly-once transport promise and no global ordering promise.
- Default/non-retry-safe handlers record an intent marker before invocation.
  An interrupted or uncertain effect is not invoked again; recovery records
  FAILED and can continue independent subscribers. This intentionally favors
  safety over blind repetition. Production Gate subscribers are idempotent and
  explicitly retry-safe.
- Cancelled dispatch releases its claim to PENDING with progress preserved. A
  process crash leaves a lease recoverable on expiry, not a permanently stuck
  claim. Terminal failures retain evidence; no distributed dead-letter system or
  automatic unlimited retry is introduced.

## Scheduler semantics

One-shot, fixed INTERVAL (1 second through 366 days) and DAILY local-wall-time
recurrences form the baseline. The original UTC anchor and IANA zone are durable.
`resolve_local` converts human local time to UTC: ambiguous input uses explicit
`datetime.fold`, nonexistent local time fails. DAILY recurrence uses the first
fold and skips a nonexistent wall-time day. INTERVAL represents elapsed time,
not local calendar time. `tzdata` makes the same rules available on Windows.

The HTTP API requires an aware `due_at` plus IANA timezone. A caller accepting
human wall time first resolves it with `resolve_local`; the Gate does not add NLP.

Due selection, deterministic occurrence UUID (`schedule ID + due instant`),
outbox insert and schedule advancement happen in **one transaction**. Two workers
cannot both advance the same due occurrence. There is no committed intermediate
schedule claim to lose between claim and completion. A crash before commit rolls
everything back; after commit, durable event delivery owns the remaining work.

Missed one-shot: one logical occurrence, then COMPLETED. Missed recurring:
emit one overdue occurrence and compute the first valid future instant, skipping
the backlog. No catch-up storm. Large forward jumps coalesce; backward clock
jumps cannot reemit an occurrence already advanced. Async wakeups merely check
the durable state every 0.5 seconds, including after Windows sleep/resume.

Cancellation serializes with due selection and event claims. It cancels future
timing and still-PENDING occurrences. A handler whose event was already claimed
has begun dispatch and is not retrospectively undone; acknowledgement of cancel
does not undo a delivered notification. Cancel Task continuations through
TaskRuntime, not Scheduler.cancel; the scheduler observes Task cancellation.

## WAITING_SCHEDULE and authority

Root calls existing TaskRuntime.create_task with `wait_until` and a timezone.
The normal Task claim first enters RUNNING, then atomically persists
WAITING_SCHEDULE + Schedule + the existing ToolCall continuation. No grant is
created. Due advancement emits TaskScheduleDue. Its handler validates the
persisted occurrence and moves the existing Task to QUEUED. TaskRuntime then
claims and executes it through ExecutionRuntime, including fresh Policy and
grant checks. A revoked grant therefore prevents execution at wakeup.

Repeated wakeups cannot create another Task or concurrent local runner. Startup
can resume queued continuations from the database. An interrupted RUNNING Tool
effect becomes PAUSED with `SCHEDULE_RECONCILIATION_REQUIRED`, not a blind retry.
Full general Task recovery is still I12; this Gate handles its own durable wait
and makes uncertain effects explicit.

## Attention and Local Client Boundary

The four projections are TaskCompleted, ReminderDue, PermissionRequested and
SubsystemDegraded. Task terminal state and pending confirmations are reconciled
from their existing operational records into deterministic events in bounded
batches. This also covers a restart between a source-state commit and projection;
it avoids coupling every Task/confirmation producer to a UI. Task completion
identity includes its completion timestamp, so a later retry can notify again.

Notification identity is deterministic per event and constrained unique. State
is PENDING until explicit ACKNOWLEDGED; transport success is not user attention
and does not clear pending state. Notification acknowledgement is audited but
does not approve a confirmation or create a Grant. Confirmation approval remains
the existing authenticated, session-scoped flow.

The existing Local Client Boundary gains authenticated reminder creation/query/
cancellation and notification query/acknowledgement/NDJSON stream endpoints.
The model remains single-local-user: authenticated replacement client sessions
can recover pending attention, without inheriting approval rights for another
session's confirmation. No Desktop Client implementation is included.

Streaming subscribes before pending-state sync, covering reconnect/creation
races. Stable IDs permit duplicate delivery; clients deduplicate and paginate
pending queries (100 per page). Each live queue is bounded to 64 IDs; overflow
closes the stream and requires resync, never discarding durable notification
state. Revoked sessions stop receiving payloads. No connected client is needed
for scheduling or notification creation.

Health remembers each component's last status durably. Repeated identical
DEGRADED observations do not spam, including after restart. Recovery updates the
state and a later degradation can notify again. Scheduler failures are visible
in Core health even when the other services continue; raw exception details are
not exposed as notification contents.

## Verification and bounded deferrals

Tests use temporary migrated Operational Stores, injected clocks, deterministic
Tools and loopback HTTP only. They cover Core recreation from the same database,
missed schedules, recurrence/DST, clock jumps, competing workers, rollback before
commit, delivery interruption/lease expiry, cancellation, uncertain non-retry-safe
effects, Policy denial after grant revocation, notification replay/identity,
real HTTP streaming, reconnect, confirmation approval separation and health
deduplication. Exact final commands, totals, commit and remote run evidence are
maintained in the Slice 07 Execution Ledger.

Non-blocking deferrals: retention/compaction of old outbox and acknowledged rows,
operator-driven terminal-event retry/reconciliation UX, distributed coordination,
full I12 recovery and broader calendar/attention policy. None is needed for the
local bounded semantics implemented here. No new architectural divergence;
nominal choices (one discriminated Event, interval/daily recurrence, pending/ack
notification states and reconciliation instead of intrusive producer callbacks)
are within the approved Slice's alternatives.
