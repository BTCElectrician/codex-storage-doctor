# Security policy

Codex Storage Doctor operates near private diagnostic data and supports a
deliberate SQLite schema mutation. Privacy leaks, target confusion, unsafe
backup behavior, and bypasses of mutation gates are security issues.

## Supported versions

This is a public alpha. Source tag `v0.1.1` and the current `main` development
line receive safety fixes. There is no binary GitHub release bundle,
package-index release, public plugin release, or long-term support promise.
Build only from a pinned source checkout you have reviewed.

## Reporting a vulnerability

If the repository's **Security → Report a vulnerability** flow is available,
use it.

No private email address or alternate confidential channel is published yet.
Do not put sensitive details in a public issue. If private reporting is not
available, report only that a confidential channel is needed and wait for the
maintainer to provide one before sharing reproduction details.

Never send:

- a real Codex SQLite database, WAL/SHM file, backup, or rollback artifact;
- `feedback_log_body`, `message`, prompts, tool inputs, or conversation text;
- secrets, tokens, environment contents, thread IDs, or process UUIDs;
- an unredacted absolute home path, configuration file, or process command
  line.

Use a minimal synthetic fixture and replace private values with obvious
placeholders.

## High-priority vulnerability classes

- a read-only command mutates Codex row or schema data;
- a wrong path creates a new database;
- any output includes forbidden payload or identity fields;
- `apply` or `rollback` proceeds while Codex may be open or process detection
  failed;
- a Windows/WSL cross-boundary target can be mutated;
- a remote or unknown filesystem target can be mutated;
- stale-plan, file-identity, schema, or trigger-conflict checks can be bypassed;
- mutation occurs before a complete verified backup;
- a post-commit failure hides that mutation occurred or omits usable recovery
  coordinates;
- rollback drops a trigger it does not exactly own;
- permissions expose a backup or manifest beyond the user where restrictive
  permissions are supported;
- shell or path handling permits command injection or writing outside the
  reviewed artifact root;
- a support report includes absolute paths without explicit opt-in.

## Response expectations

The maintainer will first confirm receipt through the available private
channel, reproduce with synthetic data, assess whether users need an immediate
stop-use warning, and prepare a bounded fix and regression test. No response
time or disclosure timeline is promised during the public alpha.

Please do not publicly disclose an unresolved issue that could expose private
Codex diagnostic content or bypass mutation gates until a safe reporting path
and remediation plan exist.
