# Codex Storage Doctor — load-bearing implementation plan

Status: architecture frozen after independent peer challenge and reconciliation
Plan date: 2026-07-24 (America/Chicago)
Repository owner: this dedicated repository root
Primary planner: `gpt-5.6-sol`, Codex Desktop subagent surface, `xhigh` effort
Peer challenger: `claude-fable-5`, Claude Code print surface, `high` effort
Oracle: not invoked and not authorized

## 1. Outcome and ownership

This new, dedicated repository is the smallest correct owner. The product is a
standalone public diagnostic and preservation tool; it does not belong inside
an Ohmni product runtime, HQ control plane, or the private Codex data directory.
The current generated workspace is locally writable, contains no product code
to preserve, and can become the public repository without modifying any
existing repo.

The repository will deliver:

1. a deterministic, standard-library Python CLI named
   `codex-storage-doctor`;
2. one concise Codex skill that routes diagnosis, planning, externally run
   mitigation, rollback, and verification;
3. one minimal Codex plugin that distributes that skill;
4. synthetic schema/path fixtures and cross-platform tests;
5. safety, evidence, competition, contribution, and launch/demo documentation.

The repository is local only in this run. It will not be published, pushed,
installed into the operator's live Codex configuration, or used to modify any
real Codex database.

## 2. Product promise

The product answers five questions in order:

1. Where could Codex diagnostic databases exist on this machine?
2. Which database is configured, open by a Codex process, recently changing,
   or merely a stale duplicate?
3. What logical SQLite activity is observable without reading private payloads?
4. What reversible mitigation would be applied, and what would it suppress?
5. After a separately authorized change, what was installed and what changed
   during a bounded observation?

It does not claim to measure physical NAND writes, establish SSD causation, or
eliminate every disk write. It never queries or prints `message`,
`feedback_log_body`, tool inputs, prompts, conversation text, or arbitrary
private payload columns.

## 3. Verified evidence baseline

Public claims will be bounded to primary sources reviewed on 2026-07-24:

- openai/codex issue 28224 was opened 2026-06-14 and closed
  2026-07-12. Its 37 TB in 21 days and approximately 640 TB/year are reporter
  measurements, not OpenAI benchmarks or universal rates.
- OpenAI merged PRs 29432, 29457, and 29599 on 2026-06-22/23 to stop
  per-WebSocket persistence, filter noisy targets, and reject bridged log
  events. PRs 31789–31792 were merged 2026-07-09 to further reduce RMCP, MCP,
  Hyper, and streamed-response logging.
- Codex 0.145.0 was released 2026-07-21. Issue 35092, opened 2026-07-24 and
  still open at plan time, reports per-SSE TRACE persistence during active
  WSL turns. Its rates are reporter observations.
- Codex 0.145.0's `logs` schema contains an AUTOINCREMENT `id`, timestamps,
  `level`, `target`, payload/body fields, thread/process identifiers, and
  `estimated_bytes`. The log sink batches inserts and prunes retained
  partitions; current source continues to use `logs_2.sqlite`.
- Current Codex source resolves SQLite storage from top-level `sqlite_home`,
  `CODEX_SQLITE_HOME`, or `CODEX_HOME`, and allows named config profiles.
- SQLite documents that `sqlite_sequence` tracks the largest historical
  AUTOINCREMENT value. It is not a count of physical device writes.
- SQLite documents `RAISE(IGNORE)` for trigger programs. A BEFORE INSERT
  trigger can suppress a row before storage, but its exact filtering semantics
  must be disclosed.
- Samsung's official 9100 PRO material rates the 4 TB model at 2,400 TBW or a
  five-year limited warranty. Approximately 693 TB over 13 months is about
  29% of 2,400 TBW. TBW is an endurance/warranty threshold, not a deterministic
  failure point.

The evidence documentation will separate:

- logical SQLite evidence: rows, AUTOINCREMENT high-water mark, DB/WAL/SHM
  sizes, and changes during a bounded sample;
- process/OS evidence: open file handles and process I/O counters when the
  platform exposes them safely;
- filesystem behavior: WAL/checkpoint and file allocation caveats;
- physical media evidence: vendor SMART/NVMe counters gathered with separate
  vendor/OS tools, not inferred by this CLI.

## 4. Competitive boundary

The product will be independently implemented. No competitor code will be
copied.

Reviewed public approaches include:

- `936917144/Codex-Log-Guard`: closest overlap; a cross-platform selective
  trigger with process gates, backup, and read-only status, but one fixed DB,
  no fixture/test suite, no multi-profile active/stale discovery, and no plugin
  package.
- `0xdefence/codexSSD`: monitoring and recoverable cleanup, but a fixed home,
  no schema-aware active database resolution, and no explicit license.
- `yangtzech/codex-logs-trigger-patch`: cross-platform trigger patch, but it
  kills Codex, replaces the DB, changes journal mode, and overstates a bounded
  verification sample.
- `taigadit/codex-tmpram`: RAM disk and persistent LaunchAgent; outside this
  product's preservation-first and no-background-job boundary.
- `IchenDEV/codex-fix`: macOS-only broader remediation including deletion and
  VACUUM; this product stays focused and non-destructive.
- `AlexJJ009/agent-tools`: cross-platform/WSL trigger support whose default is
  mutating and whose write path lacks this product's backup/process gates.
- `vibeforge1111/keep-codex-fast`: broader Codex state maintenance; this
  product will not expand into conversation, worktree, or config cleanup.
- a macOS LaunchAgent gist that persistently reapplies an all-row trigger; this
  product will not install a scheduler or watcher.

The public positioning is therefore: a preservation-first diagnostic and
evidence tool with an optional reversible mitigation, not an SSD saver,
cleanup utility, RAM-disk manager, or permanent watchdog.

## 5. Architecture

### 5.1 Language and package

Use Python 3.11+ and only its standard library at runtime.

Why:

- `sqlite3`, `tomllib`, `argparse`, `json`, `hashlib`, `pathlib`, and
  `subprocess` cover the required boundary work without an install-time
  dependency graph.
- Python is available on macOS/Linux development machines and straightforward
  to install on Windows. A normal wheel and `pipx` path provide a deterministic
  CLI without shell-specific implementations.
- One implementation can exercise Windows, WSL, macOS, and Linux path/process
  adapters in CI.
- This is a diagnostic control plane, not a high-throughput daemon. Startup
  latency and raw throughput do not justify a native runtime in v1.

Packaging:

- `pyproject.toml` using `setuptools`;
- `src/codex_storage_doctor/`;
- console script `codex-storage-doctor`;
- version `0.1.0`;
- Apache-2.0 license;
- no network calls, analytics, telemetry, or background tasks.

### 5.2 Module boundaries

- `cli.py`: argument parsing, stable exit codes, text/JSON rendering.
- `models.py`: frozen dataclasses and enums for findings, candidates, plans,
  samples, and artifacts.
- `paths.py`: candidate root/database discovery and safe path redaction.
- `config.py`: read-only TOML parsing for top-level and named-profile
  `sqlite_home` candidates.
- `processes.py`: platform adapters for process presence and database handles.
- `sqlite_inspect.py`: URI read-only connections and allowlisted metadata
  queries.
- `sampling.py`: bounded before/after logical and process-I/O deltas.
- `planning.py`: immutable plan creation, database/schema fingerprints, and
  confirmation token.
- `mitigation.py`: process-gated backup, trigger application, and rollback.
- `reports.py`: privacy-safe evidence schema and deterministic JSON.
- `privacy.py`: redaction and forbidden-field guardrails.

Modules may depend toward models/utilities. Rendering never receives raw
payload rows. SQLite inspection exposes only allowlisted aggregate values.

### 5.3 Command contract

`codex-storage-doctor audit`

- Default command and read-only default.
- Discovers candidates, inspects supported schemas, identifies process/file
  evidence, and emits a concise assessment.
- `--sample-seconds N` adds a bounded sample; default is zero.
- `--json` emits the versioned report schema.
- `--output PATH` writes the same report with mode `0600`.
- `--reveal-paths` is explicit; otherwise home prefixes and stable path IDs
  replace absolute paths.
- `--codex-home` and `--sqlite-home` may be repeated.

`codex-storage-doctor plan --database PATH --mode balanced|maximum`

- Read-only with respect to the database.
- Validates schema and current process status.
- Writes an immutable JSON plan only when `--output` is provided; otherwise
  prints the plan.
- Includes target path identity, device/inode identity, informational
  size/mtime, schema fingerprint, current tool-owned trigger state, exact SQL
  effect description, backup destination, process-gate result, and a short
  confirmation token. Size/mtime are not stale-plan gates because diagnostic
  rows can normally change between planning and a later external apply.
- A generated plan is not approval and does not change the database.

`codex-storage-doctor apply --plan PATH --confirm TOKEN`

- The only mitigation mutation command.
- Refuses stdin/piped auto-confirmation and requires the plan's exact token.
- Re-resolves the target, schema, base fingerprint, exact trigger fingerprint,
  process/file-handle gate, free space, and trigger conflicts immediately
  before writing.
- Refuses when any Codex surface appears open, when open-handle detection
  reports the target in use, or when process detection fails.
- Creates and verifies a consistent SQLite backup, then takes one exclusive
  transaction to repeat every identity/schema/process check and install the
  namespaced trigger. If anything changed during backup, mutation refuses.
- Prepares a restrictive rollback manifest before mutation and marks it
  applied after post-commit verification.
- Does not delete rows, checkpoint, change journal mode, or VACUUM.

`codex-storage-doctor rollback --manifest PATH --confirm TOKEN`

- Requires Codex closed and the exact rollback token.
- Revalidates target identity and the installed doctor-owned trigger.
- Creates a new verified backup of current state before dropping only the
  trigger named in the manifest.
- Never restores or overwrites a live DB automatically.

`codex-storage-doctor verify --database PATH --sample-seconds N`

- Read-only.
- Reports installed doctor trigger, schema, and a bounded change sample.
- Says whether a Codex process was observed and, separately, whether the
  selected database was proven open by Codex. Only a stable open-target sample
  supports “no observed logical change during N seconds”; an unproven-target
  sample explicitly says it does not demonstrate suppression.
- Accepts the rollback manifest to bind the selected database, mitigation mode,
  exact built-in trigger SQL/state, and planned/current Codex versions. Any
  mismatch makes verification partial.
- Never says “all disk writes eliminated” or converts DB deltas to TBW.

`codex-storage-doctor audit --for-support --json --output PATH`

- Produces the focused upstream/support attachment without a redundant command.
- Omits absolute paths by default and includes the evidence-layer caveats and
  exact privacy exclusions.

### 5.4 Discovery

Candidate SQLite homes are assembled in deterministic precedence order:

1. explicit repeated CLI paths;
2. `CODEX_SQLITE_HOME`;
3. `CODEX_HOME`;
4. configured top-level `sqlite_home`;
5. every named profile or `*.config.toml` SQLite home, labeled by source;
6. platform default user `.codex`;
7. WSL's Linux home and bounded Windows-user `.codex` candidates;
8. actual `logs_*.sqlite` files opened by a detected Codex process.

Discovery does not recursively search the whole disk. It inspects only
allowlisted roots and explicit paths. It recognizes `logs_*.sqlite` but marks
`logs_2.sqlite` as the currently known filename rather than assuming every
matching file is safe to mutate.

Each database receives evidence labels:

- `open_by_codex_process`: direct active evidence;
- `changed_during_sample`: observed logical/file change;
- `configured_current`: selected by current environment/config;
- `configured_profile`: configured but not proven active;
- `stale_duplicate`: a candidate with an older mtime than a different
  candidate that has direct open/change evidence;
- `unknown`: insufficient evidence.

The tool never upgrades “recent” to “active” without direct evidence. Multiple
databases may be active.

Windows/WSL cross-boundary candidates are audit-only. A Windows process may not
plan/apply/rollback a WSL/UNC database; a WSL process may not
plan/apply/rollback a database under `/mnt/<drive>`. The tool directs the user
to run on the database's native side.

### 5.5 Process adapters

- Linux/WSL: enumerate `/proc` safely, match Codex process identity without
  printing command lines, resolve `/proc/<pid>/fd` handles, and sample
  `write_bytes` when readable.
- macOS: enumerate `ps` and use `lsof` for target/open-file evidence. Parse
  command data only in memory; output PID, generic surface kind, and executable
  basename, never arguments.
- Windows: enumerate processes with standard-library
  `subprocess`/PowerShell JSON. Standard-library open-handle evidence is
  unavailable, so audit labels it partial and every mutation refuses rather
  than guessing.

Mutation gates fail closed on adapter errors. Read-only audit continues with an
explicit partial-evidence finding.

### 5.6 Privacy-safe SQLite inspection

Open existing databases using SQLite URI `mode=ro` and `PRAGMA query_only=ON`.
Do not create a database if a path is wrong. WAL read marks may touch an
existing `-shm` file; `SQLITE_READONLY_CANTINIT` becomes a partial-inspection
finding rather than a crash.

Allowed queries:

- `sqlite_master` names/types and doctor-owned trigger presence;
- `PRAGMA table_info(logs)` column names and types;
- `PRAGMA quick_check(1)`;
- `COUNT(*)`, `MAX(id)`, and sums of numeric `estimated_bytes`;
- `sqlite_sequence.seq` for the `logs` table;
- aggregate counts and numeric estimated bytes grouped into the allowlisted
  levels TRACE/DEBUG/INFO/WARN/ERROR plus `OTHER`.

Forbidden:

- selecting `message`, `feedback_log_body`, target values, file/module values,
  thread IDs, process UUIDs, or arbitrary row content;
- printing arbitrary trigger SQL;
- hashing private payloads as a substitute for redaction;
- including command lines or environment contents in evidence reports.

### 5.7 Mitigation modes

Namespaced triggers:

- `codex_storage_doctor_v1_balanced`
- `codex_storage_doctor_v1_maximum`

Balanced:

```sql
CREATE TRIGGER codex_storage_doctor_v1_balanced
BEFORE INSERT ON logs
WHEN UPPER(COALESCE(NEW.level, '')) IN ('TRACE', 'DEBUG', 'INFO')
BEGIN
  SELECT RAISE(IGNORE);
END;
```

This preserves `WARN`, `ERROR`, and unknown future levels. It suppresses known
lower-severity rows; it does not implement target-specific heuristics. Because
it references `NEW.level`, users must rollback balanced mode before upgrading
Codex and re-audit after the upgrade. The manifest records the observed Codex
version so verify can warn on a mismatch.

Maximum:

```sql
CREATE TRIGGER codex_storage_doctor_v1_maximum
BEFORE INSERT ON logs
BEGIN
  SELECT RAISE(IGNORE);
END;
```

This suppresses every diagnostic row, including WARN and ERROR. It does not
target thread/state/memory/project databases. Existing operator experience has
not observed normal-work impairment, but the product makes no zero-impact
guarantee. Feedback workflows may still retain in-memory logs or other
artifacts.

Only one doctor trigger may be installed. The base schema fingerprint excludes
doctor-owned triggers, and the exact trigger SQL is fingerprinted separately.
Applying a plan whose canonical SQL-equivalent requested trigger already
exists is a no-op success only when no other trigger conflicts. Switching
modes, altered doctor SQL, or any additional doctor-owned trigger requires
rollback and a new plan.

### 5.8 Backup and rollback artifacts

Default artifact root:

`<sqlite_home>/.codex-storage-doctor/rollback/<UTC timestamp>-<plan id>/`

The CLI warns that a full logs DB backup may contain private diagnostic
payloads. Directories use `0700`; files use `0600` where supported.

Before mutation:

1. require target and artifact path on filesystem types positively recognized
   as local; remote or unknown types are audit-only;
2. require enough free space for database plus WAL and a conservative margin;
3. run source `quick_check`;
4. create a consistent SQLite backup to a temporary file using the standard
   backup API;
5. run backup `quick_check`;
6. compute SHA-256 of the backup;
7. atomically rename the verified backup;
8. acquire an exclusive transaction, repeat process/identity/schema/trigger
   checks, then apply the trigger or refuse if anything changed.

The manifest records tool/schema versions, the observed Codex version, target
file identity and absolute path (private artifact only), backup path/hash,
trigger name/mode, base and exact-trigger fingerprints, timestamps, and
rollback token. It never records body content. It is written as `prepared`
before mutation and marked `applied` after post-commit verification, so a
crash after commit still leaves an exact rollback artifact.

Rollback drops only the exact doctor trigger after a new backup. Automatic
full-database restore is intentionally not implemented because it could
overwrite newer diagnostic data or collide with a live WAL.

## 6. Safety invariants

1. Audit, plan, verify, and evidence are read-only for Codex databases.
2. No real `~/.codex` mutation occurs in development or tests.
3. Apply/rollback require an immutable artifact plus an exact token.
4. Mutation requires Codex closed and process detection healthy.
5. Every schema mutation follows a verified backup.
6. No command deletes rows, removes sidecars, replaces a DB, checkpoints,
   changes journal mode, or runs VACUUM.
7. No persistent scheduler, service, LaunchAgent, task, cron entry, or
   environment variable is installed.
8. Only the `logs` table in an explicitly selected database can be changed.
9. Unknown schemas and conflicting triggers fail closed.
10. Private payload columns, raw unknown level values, and process arguments
    never enter output models.
11. Stable samples are described as bounded observations, not universal proof.
12. Logical, process, filesystem, and physical-drive evidence stay separate.

## 7. Exit codes

- `0`: command completed; audit may still contain non-critical findings.
- `2`: invalid CLI usage.
- `3`: no supported log database found.
- `4`: partial/unsupported inspection.
- `5`: mutation safety gate refused.
- `6`: schema unsupported or plan stale.
- `7`: backup/rollback artifact failure.
- `8`: SQLite operation failure.

JSON reports include the same symbolic status so scripts need not infer from
prose.

## 8. Tests and fixtures

Synthetic SQL fixtures:

- current `logs` schema with `feedback_log_body`;
- earlier compatible schema with `message`;
- incompatible schema missing `level`;
- future-compatible schema with an extra column;
- existing balanced/maximum trigger;
- conflicting non-doctor trigger;
- large high-water/low-retained-row state.

Synthetic path/config fixtures:

- macOS CLI/Desktop shared default;
- Linux default and custom `CODEX_HOME`;
- native Windows user home;
- WSL Linux home plus mounted Windows users;
- top-level and named-profile `sqlite_home`;
- multiple active and stale duplicate candidates.
- both directions of Windows/WSL cross-boundary audit-only discovery.

Regression coverage:

- no read-only command changes DB/WAL content or row/schema data; SQLite may
  update WAL read marks in an existing SHM file;
- no output contains seeded payload canaries, thread IDs, command arguments, or
  absolute paths by default;
- active/open/error process gates refuse mutation;
- missing targets cannot be created by any writable SQLite open;
- remote/unknown filesystems and both cross-boundary directions refuse;
- stale plans and schema changes refuse mutation;
- normal row changes after plan remain eligible and appear in the fresh backup;
- balanced preserves WARN/ERROR/unknown and blocks TRACE/DEBUG/INFO;
- maximum blocks all levels;
- exact, altered, and additional doctor-trigger states are distinguished;
- verify binds manifest, database, mode, trigger SQL/state, and version;
- backup is valid, restrictive, hashed, and created before trigger mutation;
- rollback drops only the doctor trigger and creates its own backup;
- bounded samples calculate deltas without translating them to physical writes;
- deterministic JSON ordering and schema version;
- CLI help and exit codes;
- wheel build/import/console entry point;
- dependency-free zipapp build/import/entry point;
- isolated wheel staging and byte-for-byte packaged-source verification;
- skill frontmatter and plugin manifest validation;
- leak guard over repository files.

CI matrix:

- Ubuntu, macOS, and Windows;
- Python 3.11 and latest stable supported Python;
- unit/integration tests, package build, install smoke, leak guard, manifest and
  skill validation.

Local validation must not touch the operator's live home. Tests override
`HOME`, `USERPROFILE`, `CODEX_HOME`, and `CODEX_SQLITE_HOME` to temporary
fixtures, clear ambient executable lookup, and inject fake process/version
adapters.

## 9. Skill and plugin

Skill name: `codex-storage-doctor`

The skill stays under 500 lines and tells Codex to:

1. start with `audit`;
2. explain the evidence layers and confidence;
3. never inspect private payloads;
4. generate a mitigation plan only when the user requests a change;
5. explain balanced versus maximum exactly;
6. emit a complete copyable plan/apply/verify/rollback runbook and token
   locations before asking the user to quit Codex;
7. have the user run `apply` from an external terminal after quitting all Codex
   surfaces;
8. restart Codex and run bounded verification;
9. use rollback artifacts for reversal;
10. rollback balanced mode before Codex upgrades and re-audit afterward;
11. refuse cleanup/VACUUM/background jobs because they are outside v1.

The plugin contains only:

- `.codex-plugin/plugin.json`;
- `skills/codex-storage-doctor/SKILL.md`;
- `skills/codex-storage-doctor/agents/openai.yaml`.

The plugin does not bundle an MCP server, app connector, hook, daemon, or
duplicate CLI implementation. Its manifest states that the separately
installed Python CLI is required.

A repo marketplace entry will make local installation testable without
modifying the operator's personal marketplace during development.

## 10. Documentation

- `README.md`: outcome-first audit flow, install, safety model, modes, evidence
  boundaries, current incident facts, and implemented/partial/planned table.
- `SAFETY.md`: invariants, privacy model, backup sensitivity, and exact gates.
- `EVIDENCE.md`: claim/source ledger and four evidence layers.
- `COMPETITION.md`: behavior-level comparison, license observations, and
  independent-implementation statement.
- `DEMO.md`: a 90-second synthetic demo and short launch checklist.
- `CONTRIBUTING.md`: fixture-only development, privacy/leak rules, tests.
- `SECURITY.md`: private vulnerability reporting guidance without inventing a
  contact channel; GitHub private vulnerability reporting when enabled.
- `STATUS.md`: handoff truth with implemented/partial/planned/blocked labels.

No docs will claim publication, released binaries, install counts, production
validation, SSD causation, universal rates, or zero future impact.

## 11. Implementation dependency graph

1. Evidence and schema research blocks final public claims and SQL invariants.
2. This coherent plan blocks the Fable challenge.
3. Fable challenge and Sol reconciliation block architecture freeze.
4. Package/model/privacy foundations block all platform and CLI work.
5. Discovery/process/SQLite inspection block audit and planning commands.
6. Plan artifact and process gates block apply/rollback.
7. Core commands block the skill and demo.
8. Fixtures block system-level tests.
9. Tests and docs block fresh-context Sol implementation review.
10. Accepted review fixes and a final clean validation run block handoff.

## 12. Operator gates

Explicit approval is still required for:

- publishing or pushing any repository;
- creating accounts, issues, releases, posts, or external communications;
- installing this plugin or CLI into persistent personal locations;
- applying or rolling back against a real Codex database;
- deleting logs, VACUUM, sidecar removal, DB replacement, journal changes, or
  persistent background jobs;
- changing environment variables or shell configuration;
- Oracle review.

Local repository creation, synthetic fixtures, tests, package builds, and
read-only primary-source research are authorized.

## 13. Residual risks after peer challenge

1. Whether Windows can fail closed on live DB handles using only standard
   library facilities without unreasonable false positives. Windows mutation
   remains partial/fixture-tested until real Windows execution is proven.
2. Whether repo-local marketplace path resolution matches both current Codex
   CLI and desktop app behavior; isolated validation must prove the layout.
3. Whether all named profile file forms are discoverable from current public
   config behavior without parsing unrelated private configuration.
4. Full backups can be large and contain private diagnostic payloads. V1 keeps
   the preservation-first default, rejects `VACUUM INTO`, and documents manual
   retention rather than deleting artifacts automatically.

Resolved decisions:

- Python 3.11 remains the runtime; a dependency-free `.pyz` is also built.
- Full-scan aggregates are skipped when the DB exceeds 256 MiB unless
  `--full-scan` is set.
- Unknown levels remain preserved by balanced mode but are reported as OTHER.
- Cross-boundary Windows/WSL mutation is refused.
- The base schema fingerprint excludes doctor-owned triggers; exact trigger SQL
  has a separate fingerprint.
- A synthetic integration probe proved that Python's backup API cannot run on
  the same source connection while it holds `BEGIN EXCLUSIVE`. The accepted
  sequence is verified backup first, then exclusive final rechecks and trigger
  mutation.

## 14. Definition of done

The local repository is ready for Collin's publication decision only when:

- all commands and safety invariants above are implemented or explicitly
  relabeled partial/planned;
- audit is demonstrably read-only against synthetic fixtures;
- apply and rollback work only through tokenized artifacts and verified
  backups;
- macOS/Linux/Windows/WSL paths have deterministic fixture coverage;
- privacy canaries never appear in reports or test output;
- package, skill, plugin, and marketplace validate and install in an isolated
  temporary home;
- README claims match primary sources and current implementation;
- the Fable challenge is recorded with accepted/rejected decisions;
- a fresh-context Sol `xhigh` reviewer inspects the actual diff, tests,
  invariants, deviations, and residual risks;
- accepted review findings are fixed and the full local validation is green;
- `STATUS.md` truthfully distinguishes implemented, partial, planned, blocked,
  and proposed work;
- git status is known and no external publication has occurred.
