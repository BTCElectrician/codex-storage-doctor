# Safety hardening acceptance contract

Review baseline: public commit
`450ac0f945c9a2f65a265f3bd15943ce0a186668`

Status: **required gate; not itself an acceptance verdict.**

This contract converts the independent `UNSAFE TO SHARE` review into
falsifiable release requirements. Tests use only disposable synthetic
databases and isolated homes. No test may discover, open, copy, or mutate an
operator Codex database.

## P1 requirements

| ID | MUST behavior | Adversarial proof |
| --- | --- | --- |
| APPLY-01 | Once trigger commit succeeds, every later error returns `mutation_recovery_required`, never an ordinary pre-mutation refusal. A `COMMIT` call that raises is treated as ambiguous until the exact durable trigger state is inspected. | Inject failure after the underlying commit but before the call returns, then inject failure into post-commit trigger verification. Assert the trigger exists and the result surfaces the prepared manifest path, verified backup path, every recovery-token candidate, and post-commit stage. |
| APPLY-02 | Manifest-finalization or optional result-output failure cannot hide a committed mutation. | Inject final manifest write failure and result-output write failure independently. Assert recovery coordinates are printed to stderr and the CLI exits nonzero. |
| APPLY-03 | Recovery information remains useful if the prepared and advanced manifest tokens differ. | Validate the durable manifest if readable; otherwise surface every candidate token without claiming which one is durable. |
| ROLLBACK-01 | Once trigger removal commits, every later error reports reconciliation required, never an ordinary pre-mutation refusal. A `COMMIT` call that raises is treated as ambiguous until the exact durable trigger state is inspected. | Inject commit-then-raise, connection-close, verification, manifest-finalization, and result-write failures after commit; require manifest, fresh backup, every token candidate, and post-commit stage. |
| ROLLBACK-02 | An already-absent trigger can safely reconcile a stale applied manifest. | Repeat rollback with the surfaced durable token and require exact-state verification plus a `rolled_back` manifest without another trigger mutation. |
| VERIFY-01 | A manifest binds the same database object, not merely the same path. | Replace the database at the same path, install the expected trigger, and require verification failure. |
| VERIFY-02 | A manifest binds the base schema fingerprint and requested mode. | Change the schema or provide a manifest for the other mode and require verification failure. |
| VERIFY-03 | Verification compares exact built-in trigger behavior and the complete `logs` trigger set. | Add an unrelated trigger, an additional doctor-prefixed trigger, or altered same-name SQL and require verification failure. |
| VERIFY-04 | A prepared manifest is never reported as a proven applied state. | Verify against a `prepared` lifecycle artifact and require indeterminate/nonzero status. |
| PRIVACY-01 | Non-reveal reports contain only allowlisted schema capabilities, not arbitrary SQLite identifiers or declared types. | Put POSIX, Windows, and UNC path canaries in synthetic column names/types and prove they do not appear. |
| PRIVACY-02 | Configuration/profile labels cannot carry private values into reports. | Put path canaries and control characters in synthetic profile names and prove output uses a generic source label. |
| PRIVACY-03 | Value-level redaction is recursive and fail closed, including POSIX paths, drive paths, backslash UNC paths, and forward-slash UNC paths. | Seed path canaries including `//server/share/private` in arbitrary nested report strings and require redaction or serialization refusal. |
| PRIVACY-04 | Payload-bearing values remain structurally unavailable. | Seed `feedback_log_body`, `message`, target, module, file, thread, and unknown-level canaries and scan every output mode. |
| PROCESS-01 | Target-handle detection considers all visible processes, regardless of basename. | Model a generic `node`, IDE host, Python, or SQLite process holding the selected database and require mutation refusal. |
| PROCESS-02 | Codex-surface discovery and all-process target-handle discovery remain separate facts. | A generic holder must block mutation without being mislabeled as a Codex surface. |
| PROCESS-03 | Incomplete relevant handle enumeration fails closed. | Inject `/proc`, `lsof`, permission, timeout, malformed PID/name records, orphaned file records, and parse failures and require partial/error evidence plus mutation refusal. |
| PROCESS-04 | Platform boundaries remain explicit. | Linux/macOS adapters receive synthetic holder fixtures; native Windows and cross-boundary Windows/WSL mutation remain fail-closed. |
| PROCESS-05 | The doctor may exclude only its own exact process handle from the second mutation gate; every other holder still blocks. | Model the current PID alone, another PID alone, and both together. Require self-only progress and refusal whenever the other PID is present. |

## P2 requirements

| ID | MUST behavior | Acceptance proof |
| --- | --- | --- |
| CLAIM-01 | The PATH CLI version is labeled advisory and never described as the identity of a Desktop/IDE writer. | Search README, safety, plan, skill, and CLI output for the bounded wording. |
| CLAIM-02 | Main/WAL race detection is described as identity/size/high-resolution-mtime bounded, not exact. | Documentation states the same-size/coarse-timestamp limitation. |
| CLAIM-03 | Trigger claims cover targeted inserts only. | Documentation and agent language say the pruning statement may still execute and never claim every SQLite transaction or disk write stops. |
| CLAIM-04 | Self-digests are integrity checks, not authenticity signatures; lifecycle manifests are not called immutable. | Search current user-facing documentation and CLI output. Historical review records may retain the words they originally used. |
| HYGIENE-01 | Common private plan, report, manifest, result, backup-root, and database artifacts are ignored. | Test `.gitignore` patterns and run `git check-ignore` over representative filenames. |
| HYGIENE-02 | Security instructions describe the current public alpha and a safe confidential-reporting fallback. | Review `SECURITY.md`; no stale unpublished/future-publication wording remains. |
| BUILD-01 | Hosted actions and Python build tools are pinned. | Workflow actions use immutable SHAs; `setuptools` and `wheel` use exact versions. |
| BUILD-02 | Repeated builds from the same tree are byte-identical. | Build the wheel twice and zipapp twice in separate temporary directories and compare bytes. |
| BUILD-03 | Packaged module inventory and bytes match current source. | Existing artifact verifier passes after a fresh build. |
| BUILD-04 | Source, wheel, and zipapp entry points propagate every handled nonzero CLI result to the operating system. | Run a deterministic failure through the root zipapp `__main__.py` and require the documented nonzero exit; inspect root-entrypoint parity during artifact verification. |

## Preservation regression gate

The earlier safety invariants remain mandatory:

- audit, plan, and verify do not change Codex row or schema data;
- a missing or replaced target is never created;
- apply and rollback touch only one exact doctor-owned trigger after a verified
  backup;
- no row deletion, sidecar removal, checkpoint, journal-mode change, database
  replacement, restore, or `VACUUM`;
- no environment mutation, scheduler, daemon, watcher, or persistent job;
- balanced preserves `WARN`, `ERROR`, and unknown levels while suppressing
  `TRACE`, `DEBUG`, and `INFO`; maximum suppresses all future diagnostic rows;
- rollback creates a fresh backup and refuses altered ownership/state;
- logical SQLite, process/OS, filesystem, and physical-drive evidence remain
  separate.

## Coverage accounting

| Group | MUST requirements | Required automated | Required fresh review |
| --- | ---: | ---: | ---: |
| Post-commit recovery | 3 | 3 | 3 |
| Post-commit rollback reconciliation | 2 | 2 | 2 |
| Exact verification | 4 | 4 | 4 |
| Privacy | 4 | 4 | 4 |
| Process/handle gate | 5 | 5 | 5 |
| Claims and artifact hygiene | 6 | 4 | 6 |
| Build provenance/reproducibility | 4 | 4 | 4 |
| Preservation regressions | 8 | 8 | 8 |
| **Total** | **36** | **34** | **36** |

The two claim-policy checks that are primarily review-based must still have
targeted repository searches in the release evidence. No requirement may be
silently skipped; an unsupported platform must produce an expected fail-closed
result rather than a passing mutation result.

## Release decision

General-use sharing is allowed only when:

1. every P1 requirement has a synthetic regression that first reproduces the
   old failure and then passes against the correction;
2. `make check` passes from a clean source snapshot;
3. the hosted macOS, Ubuntu, and Windows matrix passes;
4. a fresh-context adversarial reviewer examines the actual diff and returns
   `SAFE TO SHARE` or explicitly bounded `SAFE WITH CONDITIONS`;
5. the public branch equals the reviewed commit; and
6. branch protection, tag/signing policy, and any package/plugin release remain
   separate operator-controlled publication decisions.

Passing tests alone is not authority to mutate a real Codex database, publish a
package/plugin release, or claim zero future impact.
