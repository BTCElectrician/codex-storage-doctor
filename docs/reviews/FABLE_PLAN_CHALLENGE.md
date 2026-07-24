# Fable plan challenge

Date: 2026-07-24
Reviewer: `claude-fable-5`
Surface: Claude Code `2.1.170`, print mode
Effort: `high`
Authority: assessment only; no edits, mutations, publication, installation, or
Oracle escalation
Input: `docs/PLAN.md` and `STATUS.md`

## Verdict

Conditional ship. The plan was sound in ownership, scope, privacy posture, and
safety framing. Fable required three P0 amendments before architecture freeze
and proposed additional P1/P2 improvements.

## P0 findings

### P0-1 — refuse cross-boundary Windows/WSL mutation

Discovery intentionally spans WSL and Windows, but process and file-handle
adapters cannot reliably see across that boundary. A Windows-side doctor could
otherwise mutate a WSL database, or a WSL-side doctor a `/mnt/c` database,
while the native Codex writer is invisible.

Required change: cross-boundary candidates are audit-only. `plan`, `apply`, and
`rollback` must refuse with exit 5 and instruct the user to run the doctor on
the database's native side.

### P0-2 — document balanced-trigger migration coupling

The balanced trigger references `NEW.level`. A future Codex migration that
alters or drops `level` could fail while that trigger exists. A drop-and-recreate
migration could instead remove the trigger and end mitigation silently.

Required change: warn users to rollback before Codex upgrades and re-audit
afterward; record the observed Codex version in the manifest; verify must warn
on version mismatch.

### P0-3 — make idempotency compatible with stale-plan detection

Installing a trigger changes the schema, so a naive schema fingerprint makes a
second same-mode apply look stale.

Required change: exclude doctor-owned triggers from the base schema
fingerprint. A byte-identical already-installed requested trigger is a no-op
success; any other doctor or conflicting trigger still refuses.

## P1 findings

1. Close the final time-of-check/time-of-use gap by taking an exclusive SQLite
   transaction for the last identity/schema/conflict checks, verified backup,
   and trigger creation.
2. Verification must say whether a Codex process was observed during the
   sample. A stable sample while Codex is idle is not evidence of suppression.
3. Read-only WAL connections may update `-shm` read marks and may fail with
   `SQLITE_READONLY_CANTINIT` when shared memory cannot initialize. Treat that
   as partial inspection, not a crash, and do not promise unchanged SHM mtime.
4. Confirm from Codex source that a suppressed insert result is not retried.
5. Label Windows mutation support partial/fixture-tested until real Windows
   execution is proven. Add a dependency-free `.pyz` artifact to reduce
   Windows installation friction.

## P2 proposals

1. Remove the redundant `evidence` command; use
   `audit --for-support --json --output`.
2. Consider `VACUUM INTO` to compact backup copies, or explicitly reject it.
3. Bucket unknown levels as `OTHER`, use sequential report-local database IDs
   instead of path hashes, and describe `0600` as best-effort on Windows.
4. Before asking the user to quit Codex, emit a complete copyable apply,
   verify, and rollback runbook.
5. Skip expensive full-table aggregates above a deterministic size threshold
   unless `--full-scan` is set.
6. Register the repo in HQ when the operator adopts it.

## Remaining-risk positions

- Keep a full preservation-first backup by default.
- Parsing only `sqlite_home` keys with `tomllib` is adequate.
- Preserve unknown future levels in balanced mode.

## Review boundary

Fable did not replace the primary plan and did not claim operator approval.
Two optional scratch-SQLite checks were denied by its sandbox; the primary
implementation must empirically test the relevant SQLite behavior.
