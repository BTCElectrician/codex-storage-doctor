# 90-second synthetic demo

Status: commands and fixture helper are implemented. The recording and public
launch remain unauthorized and have not been created.

The demo never points at a real Codex home or diagnostic database. The first
half uses the public CLI; the mutation sequence is recorded from an external
terminal after every real Codex surface is closed. Safety-gate simulation uses
the same injected adapter seam as the regression suite and is labeled as a
test, not live process evidence.

## Pre-stage

From a source checkout:

```bash
make check
python3 scripts/create_demo_fixture.py --output work/demo-fixture
python3 -m pip install --no-deps -e .
```

The helper refuses a non-empty destination and creates:

- `work/demo-fixture/current-codex-home/logs_2.sqlite`;
- `work/demo-fixture/stale-copy/logs_1.sqlite`;
- only obviously synthetic payload canaries and level rows.

Use these exact paths. Do not set persistent environment variables. Do not
substitute a real `~/.codex`, `%USERPROFILE%\.codex`, WSL home, database,
backup, or sidecar.

## Timed script

### 0–10 seconds — the promise

Say:

> Codex Storage Doctor finds diagnostic databases, separates direct activity
> evidence from configuration clues, measures bounded logical SQLite churn
> without reading private payloads, and previews a reversible mitigation.
> Audit is the default; mutation is gated.

Show `work/demo-fixture` and say: “This is synthetic data.”

### 10–30 seconds — privacy-safe audit

Run:

```bash
HOME="$PWD/work/demo-fixture/synthetic-user" \
USERPROFILE="$PWD/work/demo-fixture/synthetic-user" \
CODEX_HOME="$PWD/work/demo-fixture/current-codex-home" \
codex-storage-doctor audit \
  --sqlite-home "$PWD/work/demo-fixture/stale-copy" \
  --sample-seconds 1
```

Point out:

- IDs are report-local and paths are redacted;
- the configured candidate is distinguished from an explicitly supplied
  duplicate;
- neither is called active or stale without direct handle/change evidence;
- only allowlisted level and numeric aggregates appear;
- DB/WAL/SHM changes are logical/file observations, not SSD TBW.

Create a support artifact and prove the seeded body prefix is absent:

```bash
HOME="$PWD/work/demo-fixture/synthetic-user" \
USERPROFILE="$PWD/work/demo-fixture/synthetic-user" \
CODEX_HOME="$PWD/work/demo-fixture/current-codex-home" \
codex-storage-doctor audit \
  --sqlite-home "$PWD/work/demo-fixture/stale-copy" \
  --for-support --json --output work/demo-support.json

if rg -q "SYNTHETIC-PRIVATE-BODY" work/demo-support.json; then
  echo "privacy check failed"
else
  echo "privacy check passed"
fi
```

### 30–50 seconds — exact preview

Run:

```bash
codex-storage-doctor plan \
  --database "$PWD/work/demo-fixture/current-codex-home/logs_2.sqlite" \
  --mode balanced \
  --output work/demo-plan.json
```

Show the selected file identity, schema fingerprint, mode effect, observed
Codex version/process context, backup root, token, and complete
external-terminal runbook. Say:

> A plan is not approval. Balanced suppresses TRACE, DEBUG, and INFO while
> preserving WARN, ERROR, and unknown future levels.

### 50–60 seconds — fail closed

Run the targeted synthetic regression:

```bash
PYTHONPATH=src:tests python3 -m unittest \
  test_planning_mitigation.MitigationTests.test_active_and_partial_process_scans_refuse_without_trigger \
  -v
```

Say:

> This is an injected process-adapter test. It proves both active and partial
> process evidence refuse before a trigger is created. It is not a live
> process measurement.

### 60–80 seconds — external apply and verification

Before recording this segment, quit every Codex Desktop, CLI, IDE, WSL, and
native counterpart. Keep the screen recording independent of Codex. Run the
exact apply command printed by the plan.

Show the verified backup hash, `rollback-manifest.json`, rollback token, and
printed verify command. Do not open the backup: it deliberately contains the
synthetic private-body rows.

After restarting Codex, run the printed verify command. The selected synthetic
database will normally not be open by that unrelated Codex session, so describe
the result honestly:

> The trigger is installed, but this stable sample does not demonstrate
> suppression during an active turn because Codex was not proven to hold this
> synthetic database open. The regression suite separately exercises bounded
> active-target sampling.

Never convert this into a zero-write claim.

### 80–90 seconds — rollback

Quit Codex again. Run the exact rollback command printed by `apply`:

```bash
codex-storage-doctor rollback \
  --manifest "<manifest-from-apply>" \
  --confirm "<rollback-token-from-apply>"
```

Show that rollback created a fresh verified backup and removed only the exact
doctor-owned trigger.

Close with:

> Diagnose first. Preserve data. Make one reversible decision at a time.

## Recording guardrails

- Keep every database and artifact synthetic.
- Never reveal a real home path, username, process argument, thread ID, prompt,
  tool input, feedback body, or backup.
- Do not say “SSD killer,” “all writes stopped,” or “zero impact.”
- Do not attribute a named person's SSD failure solely to Codex.
- Do not describe an idle or unrelated-process sample as active-target proof.
- If any command differs from `--help`, fix this document before recording.

## Launch checklist

- [x] Source install, wheel build/install, and dependency-free zipapp smoke
      locally.
- [x] Linux, macOS, and Windows process/path adapters covered by synthetic
      tests.
- [x] Windows handle evidence is explicitly partial and mutation fails closed.
- [x] WSL boundary fixtures cover both directions; cross-boundary mutation
      refuses.
- [x] Support artifacts exclude seeded payload canaries and paths by default.
- [x] Apply/rollback prove verified-backup ordering, exact ownership,
      pre-commit atomicity, and post-commit verification.
- [x] Missing-path, local-filesystem, altered/additional-trigger, manifest
      binding, and create-only output regressions pass on synthetic data.
- [x] Skill frontmatter, plugin manifest, marketplace, and isolated local
      install validate.
- [x] Hosted Ubuntu/macOS/Windows CI passes after publication.
- [x] Fresh-context Sol review has accepted the actual implementation and
      residual risks.
- [ ] Primary-source statuses and version claims are refreshed immediately
      before any package/plugin release or launch communication.
- [x] Operator explicitly authorized public repository publication.
- [ ] Operator explicitly authorizes package/plugin release and public launch
      assets.

Suggested launch assets after authorization:

1. the 90-second synthetic terminal recording;
2. one screenshot of the redacted four-layer evidence report;
3. a short post covering the problem, preservation-first distinction, bounded
   claim, and primary-source link;
4. one upstream/support-ready synthetic report example.

None of those public assets have been created or published.
