# Sol reconciliation of the Fable challenge

Date: 2026-07-24
Primary planner: `gpt-5.6-sol`
Surface: Codex Desktop subagent
Effort: `xhigh`

## Accepted

- **P0-1:** accepted. Cross-boundary Windows/WSL paths are audit-only because
  native process visibility and SQLite locking cannot be proven across the
  boundary.
- **P0-2:** accepted. Balanced mode has a real schema-migration coupling because
  it references `NEW.level`. Plans/manifests record the observed Codex version;
  docs require rollback before upgrades and re-audit afterward.
- **P0-3:** accepted. The base schema fingerprint excludes doctor-owned
  triggers, while exact trigger SQL has its own fingerprint.
- **P1-4:** accepted in goal and revised after an empirical implementation
  probe. Python's SQLite backup API hung when the same source connection held
  `BEGIN EXCLUSIVE`. The safe sequence is a consistent verified backup, then
  one exclusive transaction that repeats every process/identity/schema/trigger
  check before mutation. Any change during backup refuses the trigger.
- **P1-5:** accepted. Verification distinguishes active-process and idle
  samples.
- **P1-6:** accepted. `-shm` read marks are an allowed implementation-level
  side effect of logical read-only inspection; `READONLY_CANTINIT` is partial.
- **P1-7:** accepted and source-confirmed. Codex 0.145.0 awaits SQLite
  `execute`, ignores the returned row count, prunes, and commits; there is no
  insert retry on a zero-row `RAISE(IGNORE)` result.
- **P1-8:** accepted. Python 3.11 remains the runtime; a `.pyz` build is added;
  Windows mutation is labeled partial/fixture-tested until real Windows
  validation.
- **P2-9:** accepted. The separate `evidence` command is removed.
- **P2-11:** accepted. Unknown level values are reported only as `OTHER`; path
  IDs are sequential within each report; Windows permission limitations are
  explicit.
- **P2-12:** accepted. The skill emits the complete external-terminal runbook
  before the user quits Codex.
- **P2-13:** accepted. Full scans are skipped above 256 MiB unless explicitly
  requested.

## Rejected

- **P2-10 (`VACUUM INTO`):** rejected for v1. Even though it writes a separate
  destination, it invokes SQLite's VACUUM machinery against the source and
  expands the product's most sensitive maintenance boundary. The standard
  SQLite backup API is easier to explain and verify. Backup size and manual
  retention are documented instead.

## Deferred

- **P2-14 (HQ registration):** deferred to operator adoption. The current
  repository is a local, unpublished candidate and modifying the separate HQ
  registry is outside this repository's implementation scope. Publication or
  adoption can open that explicit change.

## Architecture freeze

With all P0 findings and the accepted P1 changes integrated into
`docs/PLAN.md`, the v1 architecture is frozen for implementation. New ideas
must fix a demonstrated invariant/test failure or be labeled post-v1.
