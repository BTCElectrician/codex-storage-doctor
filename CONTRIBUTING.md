# Contributing

This repository accepts bug reports and concrete reproductions. Its maintainer
does not directly merge outside contributions; see the policy below.

## Safety boundary for development

All development and tests must use synthetic fixtures in disposable temporary
directories.

Never:

- inspect, copy, attach, commit, or mutate a real `~/.codex`,
  `%USERPROFILE%\.codex`, WSL Codex home, or operator database;
- add real prompts, tool inputs, conversation text, `feedback_log_body`,
  thread IDs, process UUIDs, usernames, absolute home paths, or secrets to a
  fixture;
- run deletion, `VACUUM`, checkpoint, journal-mode changes, sidecar removal,
  database replacement, or persistent background jobs;
- make tests depend on a developer's actual processes, home, config, or
  network;
- weaken process, schema, identity, token, backup, or cross-boundary gates to
  make a test pass.

Tests override `HOME`, `USERPROFILE`, `CODEX_HOME`, and `CODEX_SQLITE_HOME`,
and inject fake process adapters. Payload canaries must be obviously synthetic
and must never appear in CLI output or report artifacts.

## Local checks

Target development runtime: Python 3.11+. The local validation entry point is:

```bash
make check
```

Build and smoke the two dependency-free distribution paths with:

```bash
make build
make zipapp
python dist/codex-storage-doctor.pyz --version
```

Before proposing a change:

- add a regression test at the relevant system boundary;
- keep runtime dependencies at zero unless the architecture is explicitly
  reconsidered;
- verify deterministic JSON ordering and documented exit codes;
- run package, zipapp, skill, plugin, and isolated-home validation when
  affected;
- run `git diff --check`;
- update implementation labels rather than implying an unverified feature is
  complete.

## Useful reports

A good bug report includes:

- OS and whether the database is native, WSL, or mounted across a boundary;
- Python and Codex versions;
- exact doctor command and exit code;
- redacted `audit --for-support --json` output, after manual review;
- whether Codex was observed and whether the selected database was proven open;
- expected versus actual behavior.

Do not attach a database, WAL/SHM file, backup, rollback artifact, configuration
file, raw process listing, or unreviewed report. Those may contain private
diagnostic data or paths.

For a security-sensitive report, follow [SECURITY.md](SECURITY.md).

## Scope discipline

In-scope changes strengthen:

- deterministic cross-platform discovery;
- privacy-safe aggregate inspection;
- active/stale classification;
- immutable planning and confirmation;
- process and open-handle gates;
- verified backup and exact-trigger rollback;
- bounded verification language;
- synthetic schema/path fixtures;
- skill/plugin distribution.

Cleanup, compaction, RAM disks, process killing, environment changes,
background schedulers, conversation/worktree maintenance, SMART interpretation,
and automatic database restore are outside v1.

## Contribution policy

> *About Contributions:* Please don't take this the wrong way, but I do not accept outside contributions for any of my projects. I simply don't have the mental bandwidth to review anything, and it's my name on the thing, so I'm responsible for any problems it causes; thus, the risk-reward is highly asymmetric from my perspective. I'd also have to worry about other "stakeholders," which seems unwise for tools I mostly make for myself for free. Feel free to submit issues, and even PRs if you want to illustrate a proposed fix, but know I won't merge them directly. Instead, I'll have Claude or Codex review submissions via `gh` and independently decide whether and how to address them. Bug reports in particular are welcome. Sorry if this offends, but I want to avoid wasted time and hurt feelings. I understand this isn't in sync with the prevailing open-source ethos that seeks community contributions, but it's the only way I can move at this velocity and keep my sanity.

By submitting an illustrative patch, you confirm that you have the right to
share it and have disclosed any third-party source or license that influenced
it. Do not copy code from projects with absent, unknown, or incompatible
licenses.
