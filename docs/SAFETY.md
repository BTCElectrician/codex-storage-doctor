# Safety model

Codex Storage Doctor is preservation-first. Its default operation is diagnosis,
and its optional mutation is limited to one namespaced trigger on one
explicitly selected Codex diagnostic database.

Status: implemented and regression-tested locally against synthetic data.
Publication and mutation of any real Codex database remain unauthorized.

## Non-negotiable invariants

1. `audit`, `plan`, and `verify` do not mutate Codex row or schema data.
2. A wrong path is never created as a new empty SQLite database.
3. No command deletes rows, removes sidecars, checkpoints, changes journal
   mode, replaces a database, or runs `VACUUM`.
4. No command installs a scheduler, daemon, service, LaunchAgent, cron entry,
   background watcher, or environment variable.
5. `apply` and `rollback` require an immutable artifact and its exact
   confirmation token.
6. Mutation requires every Codex surface closed and process/file-handle
   detection to succeed.
7. Every schema mutation follows a complete, verified SQLite backup.
8. Only the `logs` table in an explicitly selected database is eligible.
9. Unknown schemas, stale plans, cross-boundary Windows/WSL targets, and
   conflicting triggers fail closed.
10. Private payloads, raw unknown levels, command lines, and environment
    contents never enter report models.
11. Stable samples are bounded observations, not proof of zero writes.
12. Logical SQLite, process/OS, filesystem, and physical-drive evidence stay
    separate.
13. Mutation targets and rollback artifacts must be on a positively recognized
    local filesystem; remote or unknown filesystem types are audit-only.

## Read-only does not mean byte-for-byte inert

Existing databases are opened with SQLite URI `mode=ro` and
`PRAGMA query_only=ON`. The doctor does not write application rows or schema in
`audit`, `plan`, or `verify`.

SQLite may still update read marks in an existing `-shm` file while reading a
WAL database. If shared memory cannot be initialized, SQLite may return
`SQLITE_READONLY_CANTINIT`; the doctor treats that as partial inspection rather
than crashing or silently switching to a writable connection. Documentation
and tests must not promise an unchanged SHM modification time.

## Privacy boundary

Allowed inspection is deliberately narrow:

- `sqlite_master` object names and doctor-owned trigger presence;
- `PRAGMA table_info(logs)` column names and types;
- `PRAGMA quick_check(1)`;
- aggregate `COUNT(*)`, `MAX(id)`, numeric `estimated_bytes`, and
  `sqlite_sequence.seq`;
- aggregate level counts bucketed as `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`,
  or `OTHER`;
- file size/stat metadata and bounded deltas;
- PID, generic Codex surface kind, and executable basename where available.

Forbidden:

- `message`, `feedback_log_body`, raw target/module/file values, prompts, tool
  inputs, conversation text, thread IDs, process UUIDs, or arbitrary rows;
- raw unknown level values;
- arbitrary trigger SQL;
- hashes of payloads as a substitute for not reading them;
- process arguments or environment contents;
- absolute paths unless `--reveal-paths` is explicit.

Support reports use report-local sequential database IDs. Output files request
mode `0600`; restrictive permissions are best-effort on Windows.

## Backup sensitivity

A full backup preserves the source database, including private diagnostic
payloads already present. Backups and rollback manifests are private artifacts,
not support attachments.

The artifact root is:

```text
<sqlite_home>/.codex-storage-doctor/rollback/<UTC timestamp>-<plan id>/
```

The tool requires `0700` artifact directories and `0600` artifact files on
POSIX; Windows permissions are best-effort. Before changing a trigger, the
doctor:

1. rejects cross-boundary or non-local targets;
2. checks conservative free-space headroom;
3. runs a source quick check;
4. creates a consistent backup with SQLite's backup API;
5. runs a quick check on the backup;
6. records the backup SHA-256;
7. atomically moves the verified backup into place.

Free-space headroom covers the main database plus its current WAL. User-chosen
JSON output paths are create-only by default; the doctor refuses silent
overwrite. Only its own prepared manifest is atomically replaced when its
status advances to `applied` or `rolled_back`.

Do not upload, email, attach, or commit a backup. Retention and deletion are
manual because automatic cleanup would violate the preservation boundary.

## Mutation gates

`apply` re-resolves and compares:

- target path and device/inode file identity when the OS exposes it;
- supported `logs` schema;
- base schema fingerprint, excluding doctor-owned triggers;
- exact requested trigger fingerprint;
- current process and open-handle evidence;
- Codex version observed when the plan was created;
- free space and backup destination;
- existing doctor-owned and non-doctor trigger conflicts.

The plan also records size and mtime as informational evidence. They are not
stale-plan identity fields: a live diagnostic database can legitimately gain
rows after planning. Apply instead captures the current rows in a verified
backup after Codex is closed, then refuses if the database or WAL changes
during or after that backup.

If planning observed a Codex version, apply must observe that same version.
An unavailable apply-time version is a refusal rather than evidence that the
version is unchanged.

Writable connections use SQLite URI `mode=rw` after strict path resolution.
They cannot create a missing target.

Python's SQLite backup API cannot safely run from the same source connection
while that connection holds `BEGIN EXCLUSIVE`. The implemented ordering is:

1. preflight process, path identity, version, schema, trigger, integrity,
   permissions, and space checks;
2. a consistent read-only-source SQLite backup, backup integrity check, and
   SHA-256;
3. confirmation that the database and WAL did not change during backup;
4. a second complete process gate;
5. `BEGIN EXCLUSIVE`;
6. repeat process, file identity, schema fingerprint, trigger-conflict, and
   source-integrity checks;
7. create the one doctor-owned trigger and commit;
8. reopen read-only and verify the exact trigger.

Failure before commit leaves the target without a partial doctor trigger. A
failure after backup may leave a private verified backup for manual retention;
the tool never deletes it automatically.

A canonical SQL-equivalent requested trigger already present is a no-op
success only when no additional trigger conflicts. Altered doctor SQL,
additional doctor-prefixed triggers on any table, and switching modes require
rollback and a new plan. Reports count unexpected doctor-prefixed triggers
without printing their potentially private names or SQL.

Mutation is refused when:

- any Codex Desktop, CLI, or IDE surface appears open;
- the target is open by a Codex process;
- process/handle detection errors or is insufficient;
- a Windows process targets WSL/UNC storage, or WSL targets `/mnt/<drive>`;
- the target, schema, or plan changed;
- the schema is unsupported;
- a conflicting trigger exists;
- the verified backup or restrictive artifact cannot be created.

The user runs `apply` and `rollback` from an external terminal after quitting
Codex. A plan is only a preview; generating one is not approval to apply it.

## Exact mitigation effects

Balanced mode uses a `BEFORE INSERT` trigger that suppresses:

- `TRACE`
- `DEBUG`
- `INFO`

It preserves `WARN`, `ERROR`, and unknown future level values. Because it
references `NEW.level`, a future schema migration can invalidate it, and a
drop/recreate migration can silently remove it. Roll back balanced mode before
upgrading Codex, then re-audit and create a new plan after the upgrade.

Maximum mode uses an unconditional `BEFORE INSERT` trigger. It suppresses every
future row in the selected `logs` table, including `WARN` and `ERROR`.

Both modes suppress known SQLite insert/prune churn at that table. Neither mode:

- modifies thread, state, memory, project, or conversation databases;
- removes existing rows;
- guarantees no impact on future feedback or debugging behavior;
- prevents in-memory feedback logs or other artifacts;
- prevents every Codex or OS disk write.

## Rollback

Rollback:

1. requires Codex closed and healthy process detection;
2. revalidates target identity and exact installed trigger;
3. creates and verifies a fresh backup of the current state;
4. drops only the trigger named and fingerprinted in the manifest.

If the exact trigger is already absent and no conflicting doctor trigger
exists, rollback performs no database mutation but still seals the manifest as
`rolled_back` so the durable lifecycle record matches the observed state.

It never restores the older database automatically. An automatic restore could
overwrite newer diagnostic data or collide with a live WAL. Manual disaster
recovery from backups is outside the normal rollback path.

## Upgrade rule

For balanced mode:

1. verify that the rollback manifest is available;
2. quit Codex;
3. rollback the trigger;
4. upgrade Codex;
5. run a fresh audit;
6. create and review a new plan if mitigation is still needed.

For maximum mode, re-audit after upgrades because a migration can remove the
trigger or change the schema. Do not assume persistence.

## What verification proves

Verification reports:

- whether exact built-in doctor trigger SQL was found, or a doctor-named
  trigger was altered;
- whether a supplied manifest matches the selected database, mode, expected
  trigger state, and version context;
- the observed schema and version context;
- whether a Codex process was observed and whether it held the selected
  database open during the sample;
- logical row/high-water/file deltas during the stated interval;
- process-I/O deltas when the platform safely exposes them.

An idle stable sample does not demonstrate suppression. An active stable sample
supports only the bounded statement that no known logical change was observed
during that interval. It does not establish zero filesystem, device, telemetry,
or future writes.
