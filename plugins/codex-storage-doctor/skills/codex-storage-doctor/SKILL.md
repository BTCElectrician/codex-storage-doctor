---
name: codex-storage-doctor
description: Diagnose Codex SQLite diagnostic-log storage, distinguish active databases from stale copies, prepare reversible balanced or maximum mitigation, verify bounded results, and guide rollback. Use for suspected Codex disk-write churn, large logs_*.sqlite files, CODEX_HOME or sqlite_home confusion, or an evidence report. Do not use it for deleting logs, VACUUM, general disk cleanup, SMART diagnosis, or background-job installation.
---

# Codex Storage Doctor

Use the separately installed `codex-storage-doctor` CLI. The CLI, not this
skill, owns deterministic discovery, SQLite inspection, safety gates, backups,
and rollback artifacts.

## Hard boundaries

- Start read-only. Do not run `apply` or `rollback` unless the user explicitly
  asks for that change after seeing the exact plan.
- Never query or print values from `feedback_log_body`, `message`, prompts,
  tool inputs, thread IDs, process UUIDs, arbitrary targets, file/module
  fields, or process command arguments.
- Never delete rows or sidecars, replace a database, checkpoint, change journal
  mode, run VACUUM, change environment variables, or install a scheduler,
  service, cron entry, task, or LaunchAgent.
- Do not treat `sqlite_sequence`, DB/WAL size, or a bounded sample as physical
  SSD writes or SMART/NVMe endurance.
- Do not claim Codex caused a specific SSD failure, that mitigation removes all
  disk writes, or that it has zero future behavioral impact.
- Cross-boundary Windows/WSL candidates are audit-only. Run the doctor on the
  database's native side for planning or mutation.
- Remote and unrecognized filesystem types are audit-only. Do not override the
  CLI's native/local filesystem gate.

## Workflow

### 1. Audit

Run:

```text
codex-storage-doctor audit
```

Use `--json` when structured output helps. Use `--for-support --json --output
REPORT.json` for a redacted support/upstream artifact. Add repeated
`--codex-home` or `--sqlite-home` only for locations the user explicitly puts
in scope.

Explain the result as evidence:

- `open_by_codex_process` or `changed_during_sample`: direct active evidence;
- `configured_current` or `configured_profile`: configured, not proven active;
- `stale_duplicate`: older/unchanged while another DB has direct active
  evidence;
- `unknown`: insufficient evidence.

Keep logical SQLite activity, process/file I/O, filesystem behavior, and
physical drive health separate.

### 2. Plan only when requested

Offer exactly two modes:

- `balanced`: suppress TRACE, DEBUG, and INFO; preserve WARN, ERROR, and unknown
  future levels.
- `maximum`: suppress every SQLite diagnostic row, including WARN and ERROR.

Then run:

```text
codex-storage-doctor plan --database DB --mode balanced --output PLAN.json
```

Change `balanced` to `maximum` only if the user selects it. A plan is a preview,
not approval. Explain the chosen database, schema, exact suppressed levels,
backup location, process gate, and confirmation token.

### 3. Emit the complete external-terminal runbook

Codex must be closed before mutation, which ends this conversation. Before
asking the user to quit, provide complete copyable commands using the actual
paths/token printed by the plan:

```text
# 1. Quit Codex Desktop, CLI, IDE sessions, and WSL/native counterparts.
# 2. In an external terminal:
codex-storage-doctor apply --plan PLAN.json --confirm TOKEN
# 3. Restart Codex and exercise a normal bounded turn.
codex-storage-doctor verify --database DB --manifest MANIFEST.json --sample-seconds 10
# 4. To reverse later, quit Codex again and use the manifest/token from apply:
codex-storage-doctor rollback --manifest MANIFEST.json --confirm ROLLBACK_TOKEN
```

Do not run the mutation from the active Codex conversation.

### 4. Verification language

If the selected database was proven open by Codex during the sample, say only:

> No known diagnostic insert/prune churn was observed during this bounded
> interval.

If the selected database was not proven open by Codex, say the stable sample
does not demonstrate suppression. Pass the rollback manifest to `verify` so it
can compare the planned and current Codex versions. Never say “Codex no longer
writes to disk.”

### 5. Upgrades and rollback

Balanced mode references the `level` column and can conflict with a future
Codex schema migration. Advise rollback before upgrading Codex, then re-audit
and create a new plan after the upgrade. Maximum mode should also be re-audited
because a migration can replace the table and remove its trigger.

Rollback removes only the exact doctor-owned trigger and creates another
verified backup first. It never automatically restores an older full database.

## Stop conditions

Stop and explain the blocker when:

- process or open-handle detection is partial/error before apply or rollback;
- Codex is running;
- the schema is unsupported or changed since planning;
- the path crosses the Windows/WSL boundary;
- the target or rollback artifact filesystem is remote or not verified local;
- another trigger conflicts;
- free space or backup verification fails;
- the user requests cleanup, VACUUM, environment changes, or a persistent job.
