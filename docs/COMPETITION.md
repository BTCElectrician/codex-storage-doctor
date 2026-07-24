# Competitive boundary

Review date: 2026-07-24

Codex Storage Doctor is an independent implementation. No competitor source,
SQL, scripts, fixtures, prose, or assets were copied. Public projects were
reviewed to understand user-visible behavior, safety gaps, and positioning.

This is not a quality ranking. Each project makes different tradeoffs, and
repository behavior can change after the review date.

## Positioning

The product is a preservation-first diagnostic and evidence tool with an
optional reversible mitigation. It is not positioned as:

- an “SSD saver” with a universal wear estimate;
- a cleanup or database-compaction utility;
- a RAM-disk manager;
- a process killer;
- a persistent trigger reinstaller;
- a general Codex conversation/worktree/config maintenance suite.

## Behavior-level comparison

| Project | Public approach observed | Useful distinction in Codex Storage Doctor |
| --- | --- | --- |
| [Codex-Log-Guard](https://github.com/936917144/Codex-Log-Guard) | Cross-platform selective trigger with process gates, backup, and read-only status for a fixed database | Multi-profile discovery, active-vs-stale evidence, synthetic test matrix, immutable plan/rollback artifacts, and plugin packaging |
| [codexSSD](https://github.com/0xdefence/codexSSD) | macOS-oriented monitoring and recoverable cleanup around a fixed home | Schema-aware cross-platform discovery, privacy-safe evidence, and no cleanup in v1 |
| [codex-logs-trigger-patch](https://github.com/yangtzech/codex-logs-trigger-patch) | Cross-platform trigger scripts that stop Codex, back up/replace the DB, change journal mode, and use a short stable-ID sample | No process killing, DB replacement, journal-mode change, or zero-write inference; explicit plan and rollback gates |
| [codex-tmpram](https://github.com/taigadit/codex-tmpram) | RAM-disk relocation plus a persistent macOS LaunchAgent | No volatile relocation and no scheduler/background job by default |
| [codex-fix](https://github.com/IchenDEV/codex-fix) | Broader macOS diagnosis/remediation, including cleanup and compaction operations | Narrow diagnostic-log scope; no deletion or `VACUUM` |
| [agent-tools](https://github.com/AlexJJ009/agent-tools) | Cross-platform and WSL trigger tooling with a direct mutation path | Read-only default, immutable plan, exact token, fail-closed process gates, verified backup, and native-side-only mutation |
| [keep-codex-fast](https://github.com/vibeforge1111/keep-codex-fast) | Backup-first skill for broader Codex-state maintenance | Purpose-built diagnostic database evidence; no expansion into conversations, worktrees, or general config cleanup |

Codex Storage Doctor also recognizes a class of macOS gists that install a
LaunchAgent to keep reapplying an all-row trigger. That is intentionally outside
scope: persistent automation can silently outlive the context in which a user
approved a change.

## License cautions

GitHub repository license metadata was checked on 2026-07-24:

| Repository | GitHub license metadata at review time |
| --- | --- |
| `936917144/Codex-Log-Guard` | MIT |
| `0xdefence/codexSSD` | No detected license |
| `yangtzech/codex-logs-trigger-patch` | No detected license |
| `taigadit/codex-tmpram` | MIT |
| `IchenDEV/codex-fix` | MIT |
| `AlexJJ009/agent-tools` | No detected license |
| `vibeforge1111/keep-codex-fast` | MIT |

“No detected license” means GitHub's repository metadata returned no recognized
license at that time. It does not prove that no terms exist elsewhere, and this
table is not legal advice. In practice, an absent license is not permission to
copy. This repository therefore uses only independently written code and
documentation and links to competing work for attribution and comparison.

If a future contribution was derived from another implementation, it must not
be submitted here without a documented compatible license, precise provenance,
and a clear explanation of what was reused. Functional inspiration alone
should be restated as an independently testable requirement.

## Why not one thin trigger installer?

A trigger is only the mutation mechanism. The hard product questions are:

- Did the user identify the active database rather than a stale duplicate?
- Was any private payload inspected or leaked while diagnosing it?
- Can the tool distinguish a logical high-water mark from physical drive
  writes?
- Does it refuse to mutate a WSL database from Windows, or vice versa?
- Was Codex actually closed, and was process detection trustworthy?
- Is the backup complete, verified, restrictive, and traceable?
- Can the exact change be reversed without replacing newer data?
- Does verification state whether Codex was active and bound its conclusion to
  the sample interval?

Codex Storage Doctor exists to make those answers explicit and testable.
