# Status

Last updated: 2026-07-24 (America/Chicago)

## Current state

- **Implemented locally:** deterministic `audit`, `plan`, `apply`, `verify`,
  and `rollback`; configuration/profile/open-handle discovery; privacy-safe
  SQLite aggregates; bounded sampling; self-digested, create-only plan output
  and lifecycle-managed rollback artifacts;
  balanced/maximum triggers; verified backup ordering; exact rollback; version,
  identity, schema, process, local-filesystem, cross-boundary, permission, and
  exact-trigger gates;
  wheel/zipapp packaging; synthetic fixture generator; skill; plugin; local
  marketplace; evidence/safety/competition/demo documentation.
- **Implemented with fixture evidence:** macOS, Linux, Windows, and WSL path
  logic; macOS/Linux process/handle adapters; native Windows process presence;
  both Windows/WSL cross-boundary refusals.
- **Partial:** native Windows open-handle evidence is unavailable with the
  standard-library implementation, so native Windows mutation intentionally
  fails closed. Linux/Windows behavior is fixture-tested on native hosted
  runners, not validated against a real Codex installation.
- **Safety hardening accepted locally for `v0.1.1`:** the final adversarial
  pass found and corrected three residual boundary failures: resealed plans
  could redirect backup/permission operations, resealed manifests could
  redirect rollback artifacts, and manifest-less verification incorrectly
  reported a full match. Plans and manifests are now structurally validated
  and path-derived, backups publish without replacement, and unbound verify is
  explicitly partial.
- **Published:** public GitHub source repository and `v0.1.1` safety release
  with wheel, dependency-free zipapp, and SHA-256 checksums. The superseded
  `v0.1.0` release remains available for provenance.
- **Planned only after operator approval:** public plugin listing, demo
  recording, screenshot, external social post, and upstream communication.
- **Ready to share with documented conditions:** source and audit/remediation
  workflows passed independent review and the hosted matrix. Native Windows
  mutation remains intentionally fail-closed; all documented operator gates
  and limitations still apply.
- **Not authorized / not done:** package-index or public plugin release,
  persistent personal install, real Codex database mutation, deletion,
  `VACUUM`, sidecar removal, environment or journal-mode changes, background
  jobs, or Oracle review.

## Local validation

Current accepted evidence:

- 108 synthetic unit/integration tests pass under isolated operator-home and
  executable lookup.
- `make check` passes, including deterministic wheel/zipapp double-build tests,
  current-source and root-entrypoint artifact parity, packaged failure-exit
  propagation, compileall, leak guard over 60 text files, and distribution
  validation.
- Current local `v0.1.1` artifact SHA-256 values:
  - zipapp:
    `21054f6489927eae4ed2142094f348bac471c6fec1cb7a8c5bb602c42121e254`
  - wheel:
    `5b76645c978af2ce4fc2afa7848ae014bada9337522048ff0d54e4b3a5d1ae41`
- Independent probes cover prepared-manifest verification, concrete malformed
  `lsof` record shapes, strict self-holder near-matches, forward-slash UNC
  privacy, zipapp nonzero failures, and every unverified recovery-token
  candidate. New `v0.1.1` probes prove that resealed plans/manifests cannot
  redirect permission or backup operations and manifest-less verification
  cannot return a full-match success. Post-commit apply races cover schema
  changes, unrelated logs triggers, and doctor-prefixed triggers on other
  tables.
- `git diff --check` passes.
- No real Codex database was opened, copied, or mutated by this correction
  work.
- Hosted CI run
  [`30137226576`](https://github.com/BTCElectrician/codex-storage-doctor/actions/runs/30137226576)
  passed all six macOS, Ubuntu, and Windows jobs on Python 3.11 and 3.14 at
  safety-hardening commit
  `63384ac8f290d8251834afc9e56f1d6bc597a78c`. An earlier candidate run exposed
  two Windows-only test handle leaks; those test connections were explicitly
  closed and the complete matrix then passed.

The superseded 82-test candidate had passed its local gate and produced
artifacts, but the later adversarial review proved that it omitted
release-blocking cases. Its count and hashes are not current acceptance
evidence.

Public baseline evidence from before the current safety-hardening diff:

- 59 synthetic unit/integration tests passed on local macOS. The test runner
  isolates `HOME`, `USERPROFILE`, `CODEX_HOME`, `CODEX_SQLITE_HOME`, and
  executable lookup from the operator's Codex installation.
- Baseline `make check` passed: isolated tests, fresh-staged wheel and zipapp
  builds, byte-for-byte packaged-source verification, artifact smoke,
  compileall, leak guard, and distribution validation.
- The post-fix wheel installed without an index or dependencies into a new
  isolated virtual environment; the console `--version` smoke passed.
- Baseline artifact SHA-256 values (superseded by the unbuilt correction):
  - zipapp:
    `31723906473307601c0f0f9e67cf9b1321883d93fd73991f6da52665f5579b3e`
  - wheel:
    `d3f6a869ac6d5142428f8858804103149de070a0c48e72a5afff7d8ae5b368f2`
- Hosted CI run `30112221812` passed all six macOS, Ubuntu, and Windows jobs
  on Python 3.11 and 3.14, including tests, packaging, artifact verification,
  and install smokes.
- Repo marketplace registered and the current plugin installed/enabled under a
  fresh isolated workspace `CODEX_HOME`; the personal Codex home was not
  changed.
- Synthetic demo fixture creation and privacy-safe audit output passed with
  `HOME`, `USERPROFILE`, `CODEX_HOME`, and database roots isolated.
- `git diff --check` passed on that baseline.
- No real Codex database was mutated.

Fresh Sol accepted implementation commit
`b22c5e9b01e4ab03da1b57a465015ff0b3cdf555` for local release-candidate use.
The later hosted correction was independently reviewed and accepted before
push, but the newer adversarial review of `450ac0f` superseded that acceptance
for general-use remediation. The operator separately authorized public
repository creation, `origin/main` publication, and GitHub release artifacts.
Package-index/public plugin publication, personal installation, and
real-database mutation remain separate and were not performed by this work.

## Development-boundary note

One early local smoke command isolated `CODEX_HOME` but omitted `HOME`. Bounded
discovery therefore also found the platform-default real diagnostic database
and performed the tool's allowlisted read-only metadata inspection. It did not
select payload values, reveal its path, or mutate rows/schema; as documented,
SQLite read-only WAL access may touch existing SHM read marks. The generated
report was removed, the smoke procedure was corrected to isolate `HOME` and
`USERPROFILE`, and the corrected run found only the two synthetic databases.

## Runtime record

- Primary planner/implementer: `gpt-5.6-sol`
- Surface: Codex Desktop subagent
- Effort: `xhigh`
- Date: 2026-07-24
- Peer challenger: `claude-fable-5` on Claude Code print surface, `high`
- Initial implementation reviewer: fresh-context `gpt-5.6-sol`, `xhigh`;
  verdict **rejected**, accepted findings corrected locally
- Post-fix implementation reviewer: fresh-context `gpt-5.6-sol`, `xhigh`;
  verdict **accepted** at the earlier candidate
- Later adversarial safety reviewer: fresh-context `gpt-5.6-sol`, `xhigh`;
  initial verdict **unsafe to share** at `450ac0f`; final corrected snapshot
  verdict **SAFE WITH CONDITIONS**, with no remaining P1/P2 implementation
  blockers
- Current completion pass: independent adversarial re-review of `ee357b8`,
  three additional boundary regressions corrected for `v0.1.1`; no real Codex
  database opened, copied, or mutated
- Hosted `v0.1.1` matrix: run `30137226576`, six of six jobs passed at
  `63384ac8f290d8251834afc9e56f1d6bc597a78c`
- Oracle: not invoked
