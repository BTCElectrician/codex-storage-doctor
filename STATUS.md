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
- **Safety hardening awaiting fresh review:** a fresh independent adversarial review of
  the 82-test local candidate rejected general-use remediation. It found seven
  P1 classes: ambiguous commit outcomes, post-mutation result-output failure,
  incomplete handle parsing/timeouts, forward-slash UNC privacy, zipapp exit
  propagation, incomplete token presentation, and self-handle exclusion. The
  local correction and adversarial regression set passes; another fresh review
  remains a release gate.
- **Published:** public GitHub source repository with `main` as the default
  branch; the baseline hosted matrix passes and the current correction is
  unpushed.
- **Planned only after operator approval:** package/plugin release, demo
  recording, screenshot, launch post, and any upstream communication.
- **Blocked for general-use remediation:** fresh post-fix safety acceptance.
- **Not authorized / not done:** package or plugin release, public launch
  communication, persistent personal install, real Codex database mutation,
  deletion, `VACUUM`, sidecar removal, environment or journal-mode changes,
  background jobs, or Oracle review.

## Local validation

Current uncommitted correction evidence:

- 105 synthetic unit/integration tests pass under isolated operator-home and
  executable lookup.
- `make check` passes, including deterministic wheel/zipapp double-build tests,
  current-source and root-entrypoint artifact parity, packaged failure-exit
  propagation, compileall, leak guard over 65 text files, and distribution
  validation.
- Current local artifact SHA-256 values:
  - zipapp:
    `9bca204ed38d43554296f0cbf0326438c8c0e9fa8c83ccb91825afb2634a6aa8`
  - wheel:
    `e517b0d7610b07976a2e3ba31355683ff862f85ac285d9e0bd59ab50162401d7`
- Independent probes cover prepared-manifest verification, concrete malformed
  `lsof` record shapes, strict self-holder near-matches, forward-slash UNC
  privacy, zipapp nonzero failures, and every unverified recovery-token
  candidate. Post-commit apply races cover schema changes, unrelated logs
  triggers, and doctor-prefixed triggers on other tables.
- `git diff --check` passes.
- No real Codex database was opened, copied, or mutated by this correction
  work.
- Fresh hosted CI and post-fix adversarial review remain pending.

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
repository creation and `origin/main` publication. Package/plugin releases,
personal installation, and real-database mutation remain unauthorized.

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
  verdict **unsafe to share** for general-use remediation at `450ac0f`;
  local correction passes; fresh review pending
- Oracle: not invoked
