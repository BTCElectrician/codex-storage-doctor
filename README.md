# Codex Storage Doctor

<div align="center">

[![CI](https://github.com/BTCElectrician/codex-storage-doctor/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/BTCElectrician/codex-storage-doctor/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

</div>

**Preservation-first diagnosis and reversible mitigation for Codex SQLite
diagnostic-log churn.**

> **Repository status — public alpha.** Source tag `v0.1.1` and current
> `main` contain the reviewed implementation. Binary GitHub release assets are
> not published; build from a pinned source checkout. The current safety gate
> has 108 isolated synthetic tests plus hosted macOS, Linux, and Windows
> packaging checks. Native Windows mutation remains deliberately unavailable
> until trustworthy handle evidence can be proven. No package-index or public
> plugin listing is claimed.

## TL;DR

**The problem.** Codex diagnostic databases can be duplicated across profiles
and surfaces, and SQLite activity is easy to misread as proof of physical-drive
wear. Choosing the wrong file—or reaching for generic cleanup commands—can put
unrelated data at risk.

**The solution.** Codex Storage Doctor discovers likely diagnostic databases,
reports privacy-bounded evidence, and keeps every mitigation behind an exact
plan, closed-Codex checks, a verified fresh backup, and a narrow rollback
manifest.

| Need | What the doctor provides |
| --- | --- |
| Find the active database | Bounded discovery plus configured, open, changing, stale, and unknown classifications |
| Inspect without reading payloads | Allowlisted schema and aggregate metadata; paths redacted by default |
| Avoid overclaiming | Separate logical SQLite churn, process evidence, filesystem behavior, and physical-media health |
| Preview a mitigation | Read-only, self-digested plan bound to one explicit database, mode, schema, version, and file identity |
| Change or undo safely | Fail-closed gates, fresh verified backups, one namespaced trigger, exact verification, and trigger-only rollback |

Codex Storage Doctor is designed to answer five questions without reading your
prompts or diagnostic payloads:

1. Which Codex log databases exist?
2. Which one is configured, open by Codex, changing, or probably stale?
3. What *logical SQLite* churn is observable during a bounded sample?
4. What would a reversible mitigation suppress?
5. After an authorized change, what was installed and what changed?

It is not an SSD-health oracle, cleanup utility, RAM-disk manager, or
background watchdog. It does not claim that Codex caused any particular drive
failure, that database growth equals physical NAND writes, or that a stable
sample proves all writes stopped.

## Why this exists

An upstream report measured 37 TB of whole-drive writes over 21 days and
extrapolated about 640 TB/year while investigating Codex SQLite diagnostic
logs. Those are one reporter's measurements—not OpenAI benchmarks or a
universal Codex rate. OpenAI subsequently reduced several high-volume logging
paths, while Codex `0.145.0` source still persisted raw SSE events at TRACE and
a later issue reported active-turn SQLite writes.

The useful response is careful diagnosis, not panic:

- discover profiles and duplicate databases before choosing a target;
- inspect only allowlisted schema and aggregate metadata;
- keep logical database churn separate from OS I/O and physical drive health;
- default to read-only;
- require a plan, exact token, closed-Codex gate, verified backup, and rollback
  artifact before changing a database.

See [the source ledger](docs/EVIDENCE.md) for the evidence and
[the safety model](docs/SAFETY.md) before using a mitigation.

## Where it fits

| Approach | Best at | Built-in privacy and mutation boundaries | What it does not establish |
| --- | --- | --- | --- |
| **Codex Storage Doctor** | Codex-specific discovery, bounded SQLite evidence, and reversible trigger mitigation | Payload-column denylist, redacted paths, exact plans, closed-process gates, verified backups, and narrow rollback | Physical SSD endurance or sole causation |
| Manual `sqlite3` inspection | Ad hoc queries by an experienced operator | Depends entirely on the commands and review discipline used | Which duplicate is active, unless separately proven |
| Generic database cleanup tools | Broad deletion, compaction, or database maintenance | Not tailored to Codex diagnostic schemas or this rollback contract | Whether a Codex-specific mitigation is safe |
| SMART/NVMe and OS I/O tools | Device-health counters and system-level I/O evidence | Outside the Codex database and its contents | Which Codex table or query caused the observed history |

Use the doctor when the question is about Codex diagnostic SQLite behavior.
Use storage-health tools alongside it when the question is about the physical
device. Do not substitute one evidence layer for the other.

## Quick start

Use a pinned source checkout. There is no binary GitHub release bundle,
package-index release, or public plugin listing.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --no-deps -e .
codex-storage-doctor audit
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --no-deps -e .
codex-storage-doctor audit
```

The audit is read-only with respect to Codex databases. By default, paths are
redacted, and values from payload-bearing columns such as
`feedback_log_body` and `message` are never selected or printed.

For a bounded observation:

```bash
codex-storage-doctor audit --sample-seconds 15
```

For a privacy-safe support artifact:

```bash
codex-storage-doctor audit --for-support --json --output codex-storage-report.json
```

Reports apply field allowlists and value-level path redaction unless
`--reveal-paths` is explicit. Treat even a redacted report as potentially
sensitive metadata and review it before sharing.

## The safe workflow

`audit` is the starting point. A mitigation is a separate, deliberate flow:

```bash
# 1. Read-only: select an explicitly reviewed database and mode.
codex-storage-doctor plan \
  --database "/reviewed/path/to/logs_2.sqlite" \
  --mode balanced \
  --output doctor-plan.json

# 2. Read doctor-plan.json. It is a preview, not approval.
# 3. Copy the printed apply/verify/rollback runbook.
# 4. Quit every Codex Desktop, CLI, and IDE surface.

# 5. Run from an external terminal with the exact token from the plan.
codex-storage-doctor apply \
  --plan doctor-plan.json \
  --confirm "<token-from-plan>"

# 6. Restart Codex, exercise one normal active turn, then sample.
codex-storage-doctor verify \
  --database "/reviewed/path/to/logs_2.sqlite" \
  --manifest "/path/from-apply/rollback-manifest.json" \
  --sample-seconds 30
```

`apply` must fail closed if Codex may be open, the target is in use, process
detection fails, the schema or file identity changed, a trigger conflicts, the
plan is stale, the target/artifact filesystem is not verified local, or a
verified backup cannot be created. Writable SQLite opens use `mode=rw`, so a
disappearing or mistyped target cannot become a new empty database.

Apply also derives the only permitted private backup root from the resolved
database path. A resealed or hand-written plan cannot redirect backups or
permission changes to another directory. Rollback independently binds the
manifest and its artifact directory to that same database-owned root.

Plan identity binds the resolved path plus device/inode when the OS exposes
them. Recorded size and mtime are informational: diagnostic rows may normally
arrive between a read-only plan and a later external-terminal apply. Apply
rechecks schema, trigger state, and PATH CLI version consistency and backs up
the latest rows after Codex is closed. Its backup race check compares file
identity, size, and high-resolution mtime for the main database and WAL; this is
a conservative stat-bounded guard, not proof that every possible same-size
in-place change would be detected. The PATH CLI version is advisory context and
does not identify a separate Desktop or IDE writer.

Rollback removes only the exact doctor-owned trigger:

```bash
# Quit every Codex surface first.
codex-storage-doctor rollback \
  --manifest "/path/from-the-apply-result/rollback-manifest.json" \
  --confirm "<rollback-token-from-manifest>"
```

Rollback creates a fresh backup before dropping the trigger. It does not
overwrite the live database with an older backup.

## Safety architecture

The tool has two lanes. `audit`, `plan`, and `verify` do not mutate the selected
Codex database. `apply` and `rollback` are available only after the target,
operator, process state, filesystem, plan or manifest, and backup all pass
their gates.

```text
Known homes, profiles, configuration, and explicit roots
                         |
                         v
          Bounded discovery and classification
                         |
                         v
           Explicit logs_<n>.sqlite selection
                         |
             +-----------+-----------+
             |                       |
             v                       v
  Codex-database read-only     Authorized mutation lane
  audit -> plan -> verify      apply or rollback
             |                       |
             |              exact plan / manifest binding
             |              schema, version, and file identity
             |              Codex closed + handle evidence
             |              positively known local filesystem
             |              fresh, verified private backup
             |                       |
             v                       v
  Redacted report or plan      Exact doctor trigger + manifest
```

The doctor does not install a daemon or keep a background process running.
Plans and reports are ordinary artifacts; apply and rollback operate only when
the operator invokes them.

## Mitigation modes

| Mode | What it suppresses | What it preserves | Important cost |
| --- | --- | --- | --- |
| Audit only | Nothing | Everything | Read-only diagnosis is the default |
| Balanced | `TRACE`, `DEBUG`, and `INFO` inserts | `WARN`, `ERROR`, and unknown future levels | References `NEW.level`; rollback before upgrading Codex, then re-audit |
| Maximum | Every diagnostic row | No SQLite-backed diagnostic levels | Also blocks `WARN` and `ERROR`; no zero-impact guarantee |

Both trigger modes target only the selected diagnostic `logs` table. They do
not target Codex thread, state, memory, project, or conversation storage.
Feedback may still retain in-memory logs or other artifacts even when
SQLite-backed history is absent.

Neither mode deletes existing rows, removes WAL/SHM sidecars, checkpoints,
changes journal mode, runs `VACUUM`, changes an environment variable, or
installs a persistent job.

## What the doctor reports

The tool keeps four evidence layers separate:

| Layer | Examples | What it cannot establish alone |
| --- | --- | --- |
| Logical SQLite | row count, `MAX(id)`, AUTOINCREMENT high-water mark, estimated bytes, DB/WAL/SHM sizes and bounded deltas | physical device writes |
| Process / OS | open database handles, process presence, process I/O counters when safely available | NAND-level write amplification or sole causation |
| Filesystem behavior | WAL/checkpoint and allocation context | exact SSD endurance consumption |
| Physical media | SMART/NVMe counters from separate vendor or OS tools | which application solely caused the drive history |

`sqlite_sequence` is a historical AUTOINCREMENT high-water mark. It is not a
physical-write counter. DB and WAL sizes are not SSD TBW. A correct
post-mitigation result is bounded, for example: “No diagnostic insert or
retained-row change was observed during this 30-second interval while Codex was
proven to hold the selected database open.” It is not “Codex no longer writes
to disk,” and it does not prove that Codex stopped executing its pruning query.

## Discovery and platform scope

The target contract covers:

- macOS, Linux, native Windows, and WSL path conventions;
- Codex Desktop, CLI, and IDE process evidence where the OS exposes it safely;
- explicit `--codex-home` and `--sqlite-home` paths;
- `CODEX_HOME`, `CODEX_SQLITE_HOME`, top-level `sqlite_home`, and named
  profiles;
- configured, open, recently changing, stale, and unknown candidates;
- current `logs_2.sqlite` plus schema-aware handling of `logs_*.sqlite`.

Discovery is bounded to known and explicit roots; it does not recursively
search the whole disk. Windows-to-WSL and WSL-to-mounted-Windows targets are
audit-only because process and lock visibility cannot be proven across the
boundary.

## Command contract

| Command | Codex DB mutation | Purpose |
| --- | --- | --- |
| `audit` | None | Discover, inspect, classify, and optionally sample candidates |
| `plan --database … --mode …` | None | Create an exact, fingerprinted change preview and confirmation token |
| `apply --plan … --confirm …` | Trigger only, after gates and backup | Install one namespaced balanced or maximum trigger |
| `verify --database … --manifest … --sample-seconds …` | None | Verify exact trigger SQL and bind the observed state to its manifest/database; omitting the manifest is explicitly partial |
| `rollback --manifest … --confirm …` | Trigger only, after gates and new backup | Drop only the exact doctor-owned trigger |

Exit codes are stable in the frozen contract:

| Code | Meaning |
| --- | --- |
| `0` | Command completed; an audit may still contain non-critical findings |
| `2` | Invalid CLI usage |
| `3` | No supported log database found |
| `4` | Partial or unsupported inspection |
| `5` | Mutation safety gate refused |
| `6` | Unsupported schema or stale plan |
| `7` | Plan, backup, manifest, or rollback-artifact failure |
| `8` | SQLite operation failure |
| `9` | Apply/rollback committed or its commit outcome is ambiguous; recovery or reconciliation is required |

Use `codex-storage-doctor --help` and the subcommand help for the final
installed interface.

## Installation and packaging

Runtime target: Python 3.11+ with no third-party runtime dependencies.

No binary GitHub release bundle is currently published. Use source tag
`v0.1.1` or an exact reviewed commit, inspect it, and build locally. The build
produces:

- `dist/codex-storage-doctor.pyz`
- `dist/codex_storage_doctor-0.1.1-py3-none-any.whl`

The deterministic hashes recorded in `STATUS.md` are local and hosted-build
evidence, not a signature or a claim that matching downloadable assets exist.

From a source checkout:

```bash
python -m pip install --no-deps .
```

With `pipx`, from a source checkout:

```bash
pipx install .
```

A dependency-free zipapp is also part of the target distribution:

```bash
make zipapp
python dist/codex-storage-doctor.pyz audit
```

`make build` stages source in a fresh temporary tree so ignored incremental
build caches cannot leak stale modules into the wheel. Build inputs are pinned,
and archive timestamps, ordering, and permissions are normalized. `make check`
rebuilds both artifacts, proves repeated builds are byte-reproducible, and
compares every packaged module byte-for-byte with `src/`.

The Codex plugin package under `plugins/codex-storage-doctor/` contains the
workflow skill, not a second CLI implementation. The Python CLI must be
installed separately. Do not install the alpha plugin into a personal Codex
home merely to test it; validation uses an isolated temporary home.

## Implementation status

As of 2026-07-24:

| Area | Status | Evidence |
| --- | --- | --- |
| Ownership, evidence review, safety model, architecture | **Implemented** | Frozen plan plus independent Fable challenge and Sol reconciliation |
| Python package, wheel, and dependency-free zipapp | **Implemented locally** | Source install plus wheel/zipapp build and smoke checks |
| Audit, plan, apply, verify, rollback | **Implemented on synthetic data** | Token, schema/version/identity, local-filesystem, exact-trigger, manifest, backup, and rollback regressions |
| macOS/Linux runtime support | **Implemented; local macOS smoke** | Adapter fixtures on every host; live read-only audit smoke only |
| Native Windows audit | **Implemented / partial evidence** | Fixture-tested; process presence works but open-handle evidence is explicitly partial |
| Native Windows mutation | **Not implemented** | Fails closed until dependable handle evidence and real Windows validation exist |
| WSL discovery | **Implemented with fixtures** | Native-side operation supported by design; cross-boundary mutation is refused |
| Skill and minimal plugin | **Implemented locally** | Schema/layout validation passes; separately installed CLI remains required |
| Source repository | **Public** | `BTCElectrician/codex-storage-doctor`; `main` is the default branch |
| Source tag | **Published** | `v0.1.1` points to the reviewed source commit |
| GitHub release assets | **Not published** | Build wheel/zipapp locally from a pinned source checkout |
| Package index and public plugin listing | **Not published** | Install only from pinned, reviewed source |

See `STATUS.md` for the current handoff truth and exact validation record.

## Troubleshooting

### Exit 3: no supported log database found

Start with bounded discovery, then add only homes or database roots you have
reviewed:

```bash
codex-storage-doctor audit \
  --codex-home "/reviewed/path/to/codex-home" \
  --sqlite-home "/reviewed/path/to/sqlite-home"
```

Both options are repeatable. Discovery deliberately does not crawl the whole
disk.

### Exit 4: inspection is partial

Partial is a safety result, not a prompt to bypass a check. It can mean SQLite
could not initialize read-only WAL state, required platform evidence was
unavailable, or `verify` was run without its manifest. Inspect the bounded JSON
result:

```bash
codex-storage-doctor audit --json
```

For a fully bound mitigation check, pass the exact rollback manifest produced
by `apply`:

```bash
codex-storage-doctor verify \
  --database "/reviewed/path/to/logs_2.sqlite" \
  --manifest "/path/from-apply/rollback-manifest.json"
```

### Exit 5: a mutation safety gate refused

Quit every Codex Desktop, CLI, and IDE surface, then retry from an external
terminal. If handle visibility, filesystem locality, ownership, or a
Windows/WSL boundary remains unknown, do not override it; mutation is
intentionally unavailable in that state.

### Exit 6: the schema changed or the plan is stale

Discard the old plan. Re-run `audit`, review the selected database, and create
a new plan. Do not edit or reseal a stale plan.

### Exit 7: plan, backup, manifest, or artifact failure

Run as the database owner, confirm adequate free space, and leave the private
artifact directory in its database-derived location. The doctor will not
replace an existing backup or accept a redirected artifact root.

### Exit 9: commit outcome requires reconciliation

Do not repeat the mutation blindly. Preserve the private artifacts and inspect
the exact trigger state with `verify` and the manifest. Exit 9 means the change
committed or its commit result is ambiguous, so recovery must reconcile the
observed state first.

## Limitations

- The doctor does not read SMART/NVMe endurance counters.
- A read-only SQLite connection can update read marks in an existing `-shm`
  file. `SQLITE_READONLY_CANTINIT` is reported as partial inspection.
- Process/file-handle visibility differs by platform. Mutation fails closed
  when safety cannot be established.
- Linux and macOS mutation require successful target-directed `lsof` evidence;
  a missing or failing `lsof` leaves audit available and refuses mutation.
- Mutation is limited to recognized local filesystem types; remote, unknown,
  and cross-boundary paths remain audit-only.
- Native Windows mutation is unavailable in `0.1.1`; run read-only audit there
  and do not infer open-database handle evidence from process presence.
- Large databases skip expensive full-table aggregates by default.
- Backups may be large and contain private diagnostic payloads.
- Balanced mode is coupled to the observed `logs.level` schema.
- Maximum mode removes SQLite-backed diagnostic history, including warnings
  and errors, for future inserts while installed.
- No bounded sample proves the absence of every Codex, filesystem, or physical
  device write.

## FAQ

### Does `audit` modify my Codex database?

It does not change Codex rows, schema, triggers, journal mode, or pragmas.
SQLite may update read marks in an existing `-shm` file while opening a WAL
database read-only; the doctor reports a partial result if safe read-only
initialization is unavailable.

### Does the doctor read my conversations or prompts?

No. Payload-bearing columns such as `feedback_log_body` and `message` are
denylisted and never selected. Reports use field allowlists and redact paths by
default. Still review any support artifact before sharing it.

### Can I run it while Codex is open?

Use `audit`, `plan`, and `verify` for read-only inspection. Before `apply` or
`rollback`, quit every Codex Desktop, CLI, and IDE surface. Mutation refuses to
run when the required process and handle evidence is not conclusive.

### Should I choose balanced or maximum mode?

Start with audit only. Balanced suppresses `TRACE`, `DEBUG`, and `INFO` while
preserving `WARN`, `ERROR`, and unknown future levels, but it is coupled to the
observed `logs.level` schema. Maximum suppresses every future diagnostic row,
including warnings and errors. Roll back either mode before upgrading Codex,
then re-audit.

### Does this prove or prevent SSD wear?

No. The doctor measures bounded logical SQLite evidence and, where available,
process/filesystem context. It does not measure NAND writes, calculate drive
endurance, or prove that Codex caused a device-health observation.

### What happens on Windows or across WSL boundaries?

Native Windows read-only audit is available, but native Windows mutation is
disabled until dependable open-handle evidence exists. Windows-to-WSL and
WSL-to-mounted-Windows targets are audit-only because neither side can prove
the other side's process and lock state.

### How do I undo a mitigation?

Quit Codex and run `rollback` with the exact private manifest and rollback
token produced by `apply`. Rollback creates another verified backup, then drops
only the exact doctor-owned trigger; it never restores an older database over
the live file.

## Project documents

- [Evidence and claim ledger](docs/EVIDENCE.md)
- [Safety, privacy, backup, and rollback model](docs/SAFETY.md)
- [Safety-hardening acceptance contract](docs/reviews/SAFETY_HARDENING_ACCEPTANCE.md)
- [Independent competitive boundary](docs/COMPETITION.md)
- [90-second synthetic demo and launch checklist](docs/DEMO.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## About contributions

> *About Contributions:* Please don't take this the wrong way, but I do not accept outside contributions for any of my projects. I simply don't have the mental bandwidth to review anything, and it's my name on the thing, so I'm responsible for any problems it causes; thus, the risk-reward is highly asymmetric from my perspective. I'd also have to worry about other "stakeholders," which seems unwise for tools I mostly make for myself for free. Feel free to submit issues, and even PRs if you want to illustrate a proposed fix, but know I won't merge them directly. Instead, I'll have Claude or Codex review submissions via `gh` and independently decide whether and how to address them. Bug reports in particular are welcome. Sorry if this offends, but I want to avoid wasted time and hurt feelings. I understand this isn't in sync with the prevailing open-source ethos that seeks community contributions, but it's the only way I can move at this velocity and keep my sanity.

## License

Apache License 2.0. See [LICENSE](LICENSE).
