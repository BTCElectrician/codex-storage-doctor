# Evidence and claim ledger

Evidence review date: 2026-07-24 (America/Chicago)

This document records what Codex Storage Doctor may say publicly and what the
available evidence does **not** establish. Sources are primary for their own
contents. A GitHub issue is primary evidence of what its reporter observed, not
independent proof that the observation is universal or that its causal theory
is complete.

## The four evidence layers

Codex Storage Doctor never collapses these layers into one number:

| Layer | Direct observations | Allowed interpretation | Disallowed shortcut |
| --- | --- | --- | --- |
| 1. Logical SQLite | retained row count, `MAX(id)`, `sqlite_sequence`, numeric `estimated_bytes`, DB/WAL/SHM sizes, schema/trigger state, bounded deltas | SQLite records or files changed during the stated interval | “This many bytes reached NAND” |
| 2. Process / OS | Codex process presence, open file handles, process I/O counters where supported | a process was observed with a handle or OS-accounted I/O | “This process caused all device writes” |
| 3. Filesystem | WAL/checkpoint state, allocation and copy-on-write context from separate tools | filesystem behavior can amplify, defer, or coalesce writes | “WAL size equals SSD wear” |
| 4. Physical media | SMART/NVMe host-write and endurance counters from separate vendor/OS tools | device-reported cumulative physical-health evidence | “Codex solely caused the drive history” |

The CLI implements layers 1 and, where the platform safely exposes them, 2.
It explains layers 3 and 4 but does not synthesize them from SQLite metadata.

## Claim ledger

| Claim | Classification | Source and boundary |
| --- | --- | --- |
| Issue `#28224` reported 37 TB of whole-drive writes in about 21 days and extrapolated roughly 640 TB/year. | **Reporter measurement** | [openai/codex#28224](https://github.com/openai/codex/issues/28224). These are not OpenAI benchmarks and not a universal Codex rate. |
| Issue `#28224` opened June 14, 2026 and closed July 12, 2026. | **Repository metadata** | [Issue page](https://github.com/openai/codex/issues/28224). Closure does not prove every diagnostic-write path was eliminated. |
| OpenAI removed successful full-payload Responses WebSocket TRACE logging and related duplicate telemetry. | **Upstream source change** | [PR #29432](https://github.com/openai/codex/pull/29432), merged June 22, 2026. This concerned the WebSocket path, not every SSE path. |
| OpenAI filtered noisy bridged and mirrored targets while retaining other TRACE persistence. | **Upstream source change** | [PR #29457](https://github.com/openai/codex/pull/29457), merged June 22, and [PR #29599](https://github.com/openai/codex/pull/29599), merged June 23. |
| OpenAI further reduced RMCP, MCP tool-list, Hyper, and decoded streamed-response log volume. | **Upstream source change** | [PR #31789](https://github.com/openai/codex/pull/31789), [#31790](https://github.com/openai/codex/pull/31790), [#31791](https://github.com/openai/codex/pull/31791), and [#31792](https://github.com/openai/codex/pull/31792), all merged July 9, 2026. |
| Codex `0.145.0` was released July 21, 2026. | **Upstream release metadata** | [Official release](https://github.com/openai/codex/releases/tag/rust-v0.145.0). |
| Codex `0.145.0` source still traced each raw Responses SSE event before parsing. | **Upstream source fact** | [`responses.rs` at the `0.145.0` release commit](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/codex-api/src/sse/responses.rs#L520-L537). This establishes the code path, not a universal write rate. |
| Issue `#35092` reported continuing high-frequency SQLite writes during active turns on Codex `0.145.0` under WSL. | **Reporter observation** | [openai/codex#35092](https://github.com/openai/codex/issues/35092), open at review time. Its rates are reporter-provided; upstream source independently confirms the relevant TRACE path, not the reported rate. |
| Codex diagnostic storage uses `logs_2.sqlite`; other Codex databases have distinct names. | **Upstream source fact** | [`state/src/lib.rs`](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/state/src/lib.rs#L92-L99). This is why the doctor scopes mutation to an explicitly selected diagnostic `logs` table. |
| Codex SQLite-home precedence includes configured `sqlite_home`, `CODEX_SQLITE_HOME`, and `CODEX_HOME`. | **Upstream source fact** | [Config resolution](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/core/src/config/mod.rs#L274-L286) and [environment handling](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/core/src/config/mod.rs#L3751-L3761). Discovery is broader than one fixed `~/.codex` path. |
| `feedback_log_body` can hold private diagnostic material, including raw protocol content. | **Schema/source privacy fact** | [Schema migration](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/state/logs_migrations/0002_logs_feedback_log_body.sql#L3-L16) and the raw-SSE source above. The doctor never selects or prints values from this column. |
| Feedback can include a separate in-memory log attachment even if SQLite inserts are suppressed. | **Upstream source fact** | [Feedback ring](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/feedback/src/lib.rs#L180-L217) and [attachment path](https://github.com/openai/codex/blob/25af12f7e61572b0bc18ddb1008be543b91519b0/codex-rs/feedback/src/lib.rs#L536-L553). |
| `sqlite_sequence` records the largest historical committed ROWID for an AUTOINCREMENT table. | **SQLite specification** | [SQLite AUTOINCREMENT documentation](https://www.sqlite.org/autoinc.html). It is not a physical-write counter or an exact count of attempted inserts. |
| A SQLite trigger can use `RAISE(IGNORE)` to abandon a triggering statement without rolling back prior changes. | **SQLite specification** | [SQLite `CREATE TRIGGER`](https://www.sqlite.org/lang_createtrigger.html). The effect depends on the exact `WHEN` predicate. |
| Samsung lists the 4 TB 9100 PRO at 2,400 TBW with a five-year limited warranty. | **Vendor specification** | [Samsung 9100 PRO datasheet, revision 2.0](https://download.semiconductor.samsung.com/resources/data-sheet/Samsung_NVMe_SSD_9100_PRO_Datasheet_Rev.2.0.pdf). Samsung states that time or TBW, whichever comes first, governs the warranty boundary. |
| 640 TB/year for 13 months is about 693 TB, or about 28.9% of 2,400 TBW. | **Derived arithmetic** | `640 × 13 ÷ 12 ≈ 693.3`; `693.3 ÷ 2400 ≈ 0.2889`. This combines one reporter's extrapolation with a vendor rating. It is not an estimate of any user's actual drive writes. |

## Local incident provenance

The product was motivated by an operator-observed incident on June 25, 2026.
The operator used an unconditional SQLite `BEFORE INSERT` trigger with
`RAISE(IGNORE)`, then separately authorized row deletion and `VACUUM`. The
active logs database went from roughly 1.1 GB and 45,677 retained rows to about
40 KB.

Classification: **operator-provided observation**, not an OpenAI benchmark and
not a universal result. Deletion and `VACUUM` explain much of the size
reduction; the trigger alone should not be credited with shrinking existing
data. Codex Storage Doctor v1 intentionally does not delete rows or run
`VACUUM`.

The unconditional trigger blocks every SQLite diagnostic level, including
`WARN` and `ERROR`. Normal Codex work showed no observed impairment in that
operator experience, but zero future impact is not established.

## Claims this project will not make

- Codex definitely killed a named person's SSD. A drive failure can be real
  without sole causation being established.
- Every Codex installation has the reporter's write rate.
- Closing issue `#28224` eliminated every relevant logging path.
- A `sqlite_sequence` value is a physical-write count.
- DB or WAL size equals host writes, NAND writes, or TBW.
- A bounded stable sample proves zero future writes.
- A trigger prevents every kind of Codex disk activity.
- Maximum mode has no behavioral cost.
- TBW is a deterministic point at which an SSD fails.

## Language for reports and demos

Preferred:

> No diagnostic insert or retained-row change was observed during this bounded
> 30-second interval while Codex was proven to hold the selected database open.

This statement does not prove Codex stopped executing its pruning query.

Also acceptable:

> Logical SQLite activity was observed. Physical drive writes were not measured
> by this tool.

Avoid:

> Codex writes have been eliminated.

> The SSD is safe now.

> The high-water mark proves this many physical writes.
