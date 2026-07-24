# Sol implementation review and correction record

Review date: 2026-07-24
Reviewer: fresh-context `gpt-5.6-sol`
Surface: Codex Desktop subagent
Effort: `xhigh`
Authority: read-only assessment; no publication, installation, or real-data use

## Initial verdict

**Rejected** as a local release candidate.

The reviewer independently ran the 36-test suite and an isolated wheel build.
Both passed, but passing checks did not establish the required safety contract.
No real Codex data was inspected or changed during the review.

## Findings and primary disposition

| Priority | Finding | Disposition |
| --- | --- | --- |
| P0 | Writable `sqlite3.connect(path)` could create an empty DB if the target disappeared after preflight. | **Accepted.** Writable opens now use strict resolution plus SQLite URI `mode=rw`; a missing-path regression proves no file is created. |
| P1 | The plan recorded size/mtime but apply compared only device/inode. | **Accepted in safety goal; strict size/mtime staleness rejected.** Size/mtime are now explicitly informational because live log rows can normally arrive between plan and external apply. Device/inode, schema, version, trigger state, process closure, and verified current backup remain gates. A regression proves intervening rows are preserved in that backup. |
| P1 | An exact requested trigger could return idempotent success while another doctor-prefixed trigger also existed. | **Accepted.** Conflict checks now run before idempotent success in preflight and the exclusive transaction. |
| P1 | Mutation lacked a local-filesystem gate. | **Accepted.** Target and artifact paths must resolve to positively recognized local filesystem types; remote and unknown types fail closed. |
| P1 | Every non-active candidate was labeled stale whenever any direct-active candidate existed. | **Accepted.** `stale_duplicate` now additionally requires an older mtime than direct activity. |
| P1 | Verification checked names, not exact trigger SQL, and did not bind manifest database/mode/trigger state. | **Accepted.** Inspection separates exact and altered doctor triggers; verify validates the manifest and expected state against the selected DB. |
| P1 | Built wheel/zipapp artifacts predated source changes. | **Accepted.** Final artifacts must be rebuilt only after the correction set and post-fix review. |
| P1 | Cross-platform path and lifecycle fixture coverage was incomplete. | **Accepted.** Native Windows default, WSL Windows-home, fixture-led boundary, active/stale, no-create, trigger conflict, manifest, and local-filesystem cases were added. |
| P2 | Invalid sample durations returned input/not-found instead of argparse usage. | **Accepted.** Parsing now returns exit 2. |
| P2 | `audit --full-scan` did not flow into bounded samples. | **Accepted.** Both snapshots now receive the explicit flag. |
| P2 | Zipapp staging could include bytecode caches. | **Accepted.** Staging excludes caches and a zip-content regression checks this. |
| P2 | Top-level and selected profile roots could both be labeled current. | **Accepted.** A selected profile takes precedence; top-level remains configured but not current. |

## Residual risks retained

- Native Windows mutation remains unavailable because standard-library
  open-handle evidence is partial.
- Hosted Linux/macOS/Windows CI cannot run before publication.
- Linux and Windows behavior is fixture-tested, not live-system validated in
  this local run.
- Process identification remains intentionally conservative and basename-led.
- Primary-source statuses must be refreshed immediately before publication.

## Post-fix gate

This record does not turn the initial rejection into acceptance. A second
fresh-context Sol review must inspect the corrected source, tests, generated
artifacts, safety invariants, and residual-risk labels. Its verdict will be
appended here before handoff.

## Second-review findings corrected before final verdict

The fresh post-fix reviewer identified additional issues while inspecting the
correction set. They were accepted and corrected before asking for a verdict:

| Priority | Finding | Disposition |
| --- | --- | --- |
| P1 | Incremental wheel build state could package stale ignored `build/lib` source. | **Accepted.** Wheel construction now stages only current project metadata and `src/` in a fresh temporary tree. Both wheel and zipapp inventories and module bytes are compared with current source. |
| P1 | An unknown doctor-prefixed trigger on another table was outside exact verification and rollback conflict checks. | **Accepted.** Inspection counts every doctor-prefixed trigger without exposing arbitrary names or SQL; plan, apply, verify, and rollback fail closed on unexpected entries. |
| P1 | An already-absent trigger could return rollback success without advancing the manifest lifecycle. | **Accepted.** This idempotent branch now seals and writes `rolled_back` state and explicitly reports manifest reconciliation. |
| P1 | A plan with a known Codex version could proceed when the apply-time version became unavailable. | **Accepted.** Known-at-plan and unavailable-at-apply is now a safety refusal before backup or mutation. |
| P1 | Tests could inherit operator homes and process/version discovery. | **Accepted.** The suite runs under isolated home/Codex roots and system-only executable lookup; command tests inject process and version evidence. |
| P2 | Hosted CI omitted the newest supported stable Python line. | **Accepted.** The matrix now covers Python 3.11 and 3.14 on Ubuntu, macOS, and Windows. |
| P2 | Malformed plan/manifest JSON returned the no-database exit code. | **Accepted.** Artifact decoding now has a dedicated failure type and stable exit 7 across apply, verify, and rollback. |

The corrected tree passes 58 isolated tests and rebuilds source-matching wheel
and zipapp artifacts. These corrections still do not claim acceptance; the
reviewer's final disposition is pending.
