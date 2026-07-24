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
