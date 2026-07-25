# Codex Storage Doctor

Preservation-first diagnosis and reversible mitigation for Codex SQLite
diagnostic-log churn.

> **Repository status — public alpha.** Source tag `v0.1.1` and current
> `main` contain the reviewed implementation. Binary GitHub release assets are
> not published; build from a pinned source checkout. The current safety gate
> has 108 isolated synthetic tests plus hosted macOS, Linux, and Windows
> packaging checks. Native Windows mutation remains deliberately unavailable
> until trustworthy handle evidence can be proven. No package-index or public
> plugin listing is claimed.

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
