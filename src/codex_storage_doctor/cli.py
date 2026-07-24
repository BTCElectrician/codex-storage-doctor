"""Command-line interface for the preservation-first storage doctor."""

from __future__ import annotations

import argparse
from dataclasses import replace
import os
from pathlib import Path
import platform
import sqlite3
import sys
from typing import Any, Mapping, Sequence

from . import __version__
from .mitigation import (
    SafetyGateError,
    apply_plan,
    rollback,
    validate_manifest,
)
from .models import DatabaseCandidate, assign_candidate_report_ids
from .paths import (
    classify_candidate_activity,
    discover_candidates,
    is_cross_boundary_path,
)
from .planning import (
    CrossBoundaryError,
    PlanError,
    SafetyBoundaryError,
    create_plan,
    observed_codex_version,
    utc_now,
)
from .privacy import assert_privacy_safe
from .processes import scan_codex_processes
from .reports import (
    ArtifactReadError,
    read_json_object,
    render_json,
    write_private_json,
)
from .sampling import sample_database
from .sqlite_inspect import inspect_database


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_PARTIAL = 4
EXIT_SAFETY_REFUSED = 5
EXIT_STALE_OR_SCHEMA = 6
EXIT_ARTIFACT = 7
EXIT_SQLITE = 8


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _sample_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if seconds < 0 or seconds > 86_400:
        raise argparse.ArgumentTypeError("must be between 0 and 86400")
    return seconds


def _database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--database",
        type=_path,
        required=True,
        help="explicit reviewed logs_<n>.sqlite target",
    )


def _json_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the complete privacy-bounded JSON result",
    )
    parser.add_argument(
        "--output",
        type=_path,
        help="write the JSON result with private file permissions",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-storage-doctor",
        description=(
            "Preservation-first diagnosis and reversible mitigation for "
            "Codex SQLite diagnostic logs."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    audit = subparsers.add_parser(
        "audit",
        help="discover and inspect diagnostic databases read-only",
    )
    audit.add_argument(
        "--codex-home",
        action="append",
        default=[],
        type=_path,
        help="additional Codex home to inspect (repeatable)",
    )
    audit.add_argument(
        "--sqlite-home",
        action="append",
        default=[],
        type=_path,
        help="additional SQLite home or log database to inspect (repeatable)",
    )
    audit.add_argument(
        "--sample-seconds",
        type=_sample_seconds,
        default=0.0,
        metavar="SECONDS",
        help="bounded before/after sample per candidate (default: 0)",
    )
    audit.add_argument(
        "--full-scan",
        action="store_true",
        help="allow aggregate scans above the default 256 MiB bound",
    )
    audit.add_argument(
        "--reveal-paths",
        action="store_true",
        help="include absolute database paths in the report",
    )
    audit.add_argument(
        "--for-support",
        action="store_true",
        help="label the output as a review-before-sharing support artifact",
    )
    _json_arguments(audit)

    plan = subparsers.add_parser(
        "plan",
        help="create a read-only, fingerprinted mitigation preview",
    )
    _database_argument(plan)
    plan.add_argument(
        "--mode",
        required=True,
        choices=("balanced", "maximum"),
        help="balanced preserves WARN/ERROR/unknown; maximum blocks all rows",
    )
    _json_arguments(plan)

    apply = subparsers.add_parser(
        "apply",
        help="apply an exact plan after closed-process and backup gates",
    )
    apply.add_argument("--plan", required=True, type=_path)
    apply.add_argument("--confirm", required=True)
    _json_arguments(apply)

    verify = subparsers.add_parser(
        "verify",
        help="inspect a mitigation and take a bounded read-only sample",
    )
    _database_argument(verify)
    verify.add_argument(
        "--sample-seconds",
        type=_sample_seconds,
        default=15.0,
        metavar="SECONDS",
    )
    verify.add_argument(
        "--reveal-paths",
        action="store_true",
        help="include the absolute database path in the report",
    )
    verify.add_argument(
        "--manifest",
        type=_path,
        help="rollback manifest used to compare the planned Codex version",
    )
    _json_arguments(verify)

    rollback_parser = subparsers.add_parser(
        "rollback",
        help="drop only the exact doctor-owned trigger in a manifest",
    )
    rollback_parser.add_argument("--manifest", required=True, type=_path)
    rollback_parser.add_argument("--confirm", required=True)
    _json_arguments(rollback_parser)
    return parser


def _emit(
    result: Mapping[str, Any],
    *,
    json_output: bool,
    output: Path | None,
    text_output: str,
) -> None:
    assert_privacy_safe(result)
    if output is not None:
        target = write_private_json(output, result)
        if not json_output:
            print(f"{text_output}\nJSON artifact: {target}")
            return
    if json_output:
        print(render_json(result), end="")
    elif output is None:
        print(text_output)


def _audit_text(result: Mapping[str, Any]) -> str:
    databases = result["databases"]
    lines = [
        "Codex Storage Doctor audit",
        f"Candidates: {len(databases)}",
        (
            "Privacy: paths redacted; diagnostic bodies, thread IDs, process "
            "UUIDs, targets, modules, files, and command arguments were not read."
        ),
    ]
    for database in databases:
        candidate = database["candidate"]
        inspection = database["inspection"]
        labels = ", ".join(candidate["evidence_labels"]) or "unknown"
        lines.append(
            f"- {candidate['id']}: {inspection['status']}; "
            f"{inspection['database_size_bytes']} DB bytes; labels={labels}"
        )
        if inspection["doctor_triggers"]:
            lines.append(
                "  doctor trigger: " + ", ".join(inspection["doctor_triggers"])
            )
        if inspection["altered_doctor_triggers"]:
            lines.append(
                "  error: a doctor-named trigger failed exact SQL verification"
            )
        if inspection["unexpected_doctor_trigger_count"]:
            lines.append(
                "  error: an unexpected doctor-prefixed trigger exists"
            )
        sample = database.get("sample")
        if sample is not None:
            lines.append(
                "  bounded logical change observed: "
                + ("yes" if sample["logical_change_observed"] else "no")
            )
    scan = result["process_evidence"]
    lines.append(
        f"Process evidence: {scan['status']}; Codex observed: "
        f"{'yes' if scan['codex_running'] else 'no'}"
    )
    lines.append(
        "Scope: logical SQLite and available process evidence only; this does "
        "not measure filesystem amplification or physical drive endurance."
    )
    return "\n".join(lines)


def _run_audit(args: argparse.Namespace) -> int:
    candidates = discover_candidates(
        explicit_codex_homes=args.codex_home,
        explicit_sqlite_homes=args.sqlite_home,
    )
    paths = tuple(candidate.path for candidate in candidates)
    process_scan = scan_codex_processes(paths)
    known_paths = {
        os.path.normcase(str(candidate.path.absolute())) for candidate in candidates
    }
    added_open_candidate = False
    for open_path in process_scan.open_database_paths:
        key = os.path.normcase(str(open_path.absolute()))
        if key in known_paths or not open_path.is_file():
            continue
        known_paths.add(key)
        cross_boundary = is_cross_boundary_path(open_path)
        candidates.append(
            DatabaseCandidate(
                path=open_path.absolute(),
                report_id="",
                sources=("process:open_handle",),
                known_filename=open_path.name.lower() == "logs_2.sqlite",
                evidence_labels=("open_by_codex_process",),
                mutation_allowed=not cross_boundary,
                refusal_reason=(
                    "Run mutation commands on the database's native OS side."
                    if cross_boundary
                    else None
                ),
            )
        )
        added_open_candidate = True
    if added_open_candidate:
        candidates = list(assign_candidate_report_ids(candidates))
        process_scan = scan_codex_processes(
            tuple(candidate.path for candidate in candidates)
        )
    if not candidates:
        print(
            "No Codex diagnostic logs database was found in the bounded roots "
            "or open-handle evidence.",
            file=sys.stderr,
        )
        return EXIT_NOT_FOUND

    samples: dict[Path, Any] = {}
    changed_paths: list[Path] = []
    if args.sample_seconds:
        for candidate in candidates:
            sample = sample_database(
                candidate.path,
                args.sample_seconds,
                full_scan=args.full_scan,
            )
            samples[candidate.path] = sample
            if sample.logical_change_observed:
                changed_paths.append(candidate.path)
    candidates = list(
        classify_candidate_activity(
            candidates,
            open_paths=process_scan.open_database_paths,
            changed_paths=changed_paths,
        )
    )

    database_results: list[dict[str, Any]] = []
    incomplete = process_scan.status != "ok"
    for candidate in candidates:
        inspection = replace(
            inspect_database(candidate.path, full_scan=args.full_scan),
            report_id=candidate.report_id,
        )
        incomplete = incomplete or inspection.status != "ok" or inspection.partial
        sample = samples.get(candidate.path)
        if sample is not None and sample.status != "ok":
            incomplete = True
        database_results.append(
            {
                "candidate": candidate.to_dict(reveal_paths=args.reveal_paths),
                "inspection": inspection.to_dict(reveal_paths=args.reveal_paths),
                "sample": sample.to_dict() if sample is not None else None,
            }
        )

    result = {
        "schema_version": "codex-storage-doctor.audit.v1",
        "tool_version": __version__,
        "generated_at": utc_now(),
        "platform": platform.system(),
        "support_artifact": bool(args.for_support),
        "review_before_sharing": True,
        "privacy_boundary": {
            "absolute_paths_revealed": bool(args.reveal_paths),
            "never_selected": [
                "feedback_log_body",
                "thread_id",
                "process_uuid",
                "target",
                "module_path",
                "file",
                "process_command_arguments",
            ],
        },
        "evidence_scope": {
            "logical_sqlite": True,
            "process_os": process_scan.status,
            "filesystem_behavior": "context_only",
            "physical_media_health": "not_measured",
            "bounded_sample_not_zero_write_proof": True,
        },
        "process_evidence": process_scan.to_dict(),
        "databases": database_results,
    }
    _emit(
        result,
        json_output=args.json,
        output=args.output,
        text_output=_audit_text(result),
    )
    return EXIT_PARTIAL if incomplete else EXIT_OK


def _plan_text(plan: Mapping[str, Any], output: Path | None) -> str:
    suppressed = ", ".join(plan["suppresses"])
    preserved = ", ".join(plan["preserves"]) or "no SQLite diagnostic levels"
    lines = [
            "Mitigation plan created read-only; no database change was made.",
            f"Mode: {plan['mode']}",
            f"Suppresses: {suppressed}",
            f"Preserves: {preserved}",
            f"Backup root: {plan['artifact_root']}",
            f"Apply token: {plan['confirmation_token']}",
            (
                "Process evidence during planning: "
                + str(plan["process_gate_at_plan"]["status"])
                + "; Codex observed: "
                + (
                    "yes"
                    if plan["process_gate_at_plan"]["codex_running"]
                    else "no"
                )
                + "; apply will rescan and fail closed unless evidence is complete."
            ),
            "Before apply: save the plan, review it, copy the runbook, then "
            "quit every Codex Desktop, CLI, IDE, WSL, and native session.",
        ]
    if plan["mode"] == "balanced":
        lines.append(
            "Balanced mode is coupled to the current level column; rollback "
            "before upgrading Codex, then re-audit."
        )
    else:
        lines.append(
            "Re-audit after Codex upgrades because a migration can remove or "
            "invalidate the trigger."
        )
    if output is not None:
        plan_path = output.expanduser().resolve()
        database = Path(str(plan["database"]))
        lines.extend(
            (
                "External-terminal runbook:",
                "1. Quit every Codex surface.",
                f'2. codex-storage-doctor apply --plan "{plan_path}" '
                f'--confirm "{plan["confirmation_token"]}"',
                "3. Restart Codex, exercise one normal active turn, then run "
                f'codex-storage-doctor verify --database "{database}" '
                '--manifest "<manifest-from-apply>" --sample-seconds 30',
                "4. To reverse, quit Codex and run "
                'codex-storage-doctor rollback --manifest "<manifest-from-apply>" '
                '--confirm "<rollback-token-from-apply>"',
            )
        )
    else:
        lines.append(
            "Save a new plan with --output before applying; apply consumes the "
            "saved immutable artifact."
        )
    return "\n".join(lines)


def _run_plan(args: argparse.Namespace) -> int:
    process_scan = scan_codex_processes((args.database,))
    plan = create_plan(
        args.database,
        args.mode,
        process_observation=process_scan.to_dict(),
    )
    _emit(
        plan,
        json_output=args.json,
        output=args.output,
        text_output=_plan_text(plan, args.output),
    )
    return EXIT_OK


def _apply_text(result: Mapping[str, Any]) -> str:
    if not result.get("changed"):
        return "The exact doctor-owned trigger was already installed; no change was made."
    return "\n".join(
        (
            "Mitigation applied after a verified backup.",
            f"Trigger: {result['trigger_name']}",
            f"Backup: {result['backup']}",
            f"Rollback manifest: {result['manifest']}",
            f"Rollback token: {result['rollback_token']}",
            "Next: restart Codex, exercise one normal turn, then run verify. "
            f'Command: codex-storage-doctor verify --database "{result["database"]}" '
            f'--manifest "{result["manifest"]}" --sample-seconds 30',
            "A stable bounded sample is not proof of zero disk writes.",
        )
    )


def _run_apply(args: argparse.Namespace) -> int:
    plan = read_json_object(args.plan)
    result = apply_plan(plan, args.confirm)
    _emit(
        result,
        json_output=args.json,
        output=args.output,
        text_output=_apply_text(result),
    )
    return EXIT_OK


def _verify_text(result: Mapping[str, Any]) -> str:
    inspection = result["inspection"]
    sample = result["sample"]
    lines = [
        "Codex Storage Doctor verification",
        "Installed doctor triggers: "
        + (", ".join(inspection["doctor_triggers"]) or "none"),
        (
            f"Bounded interval: {sample['requested_seconds']} seconds; "
            f"Codex process observed: "
            f"{'yes' if sample['codex_process_observed'] else 'no'}; "
            f"selected database open by Codex: "
            f"{'yes' if sample['target_open_by_codex'] else 'no'}; "
            f"logical change observed: "
            f"{'yes' if sample['logical_change_observed'] else 'no'}."
        ),
    ]
    if inspection["altered_doctor_triggers"]:
        lines.append(
            "Error: a doctor-named trigger exists but failed exact SQL verification."
        )
    if inspection["unexpected_doctor_trigger_count"]:
        lines.append(
            "Error: an unexpected doctor-prefixed trigger exists."
        )
    if (
        inspection["doctor_triggers"]
        and sample["target_open_by_codex"]
        and not sample["logical_change_observed"]
    ):
        lines.append(
            "No known diagnostic insert/prune churn was observed during this "
            "bounded interval while Codex held the selected database open."
        )
    elif not sample["target_open_by_codex"]:
        lines.append(
            "The selected database was not proven open by Codex, so a stable "
            "sample does not demonstrate suppression during an active turn."
        )
    lines.append(
        "This does not establish zero disk writes or physical drive health."
    )
    version = result["version_context"]
    if version["mismatch"]:
        lines.append(
            "Warning: the observed Codex version differs from the mitigation "
            "manifest. Roll back, re-audit, and create a new plan."
        )
    elif version["comparison"] == "unavailable" and inspection["doctor_triggers"]:
        lines.append(
            "Version comparison unavailable; pass --manifest to check the "
            "planned Codex version."
        )
    manifest_context = result["manifest_context"]
    if manifest_context["provided"] and not manifest_context["matches"]:
        lines.append(
            "Warning: the rollback manifest does not match the selected database "
            "and exact observed trigger state."
        )
    return "\n".join(lines)


def _run_verify(args: argparse.Namespace) -> int:
    inspection = replace(
        inspect_database(args.database),
        report_id="database-001",
    )
    if not inspection.exists:
        return EXIT_NOT_FOUND
    sample = sample_database(args.database, args.sample_seconds)
    current_version = observed_codex_version()
    planned_version: str | None = None
    comparison = "unavailable"
    mismatch = False
    manifest_context: dict[str, Any] = {
        "provided": False,
        "matches": True,
        "database_matches": None,
        "expected_trigger_name": None,
        "expected_state": None,
        "exact_trigger_state_matches": None,
    }
    if args.manifest is not None:
        manifest = read_json_object(args.manifest)
        validate_manifest(manifest)
        selected_database = args.database.expanduser().resolve(strict=True)
        manifest_database = Path(str(manifest["database"])).expanduser().resolve(
            strict=False
        )
        database_matches = selected_database == manifest_database
        trigger_name = str(manifest["trigger_name"])
        status = str(manifest["status"])
        exact_present = (
            trigger_name in inspection.doctor_triggers
            and trigger_name not in inspection.altered_doctor_triggers
        )
        altered_present = trigger_name in inspection.altered_doctor_triggers
        unexpected_present = bool(
            inspection.unexpected_doctor_trigger_count
        )
        if status == "applied":
            expected_state = "present"
            trigger_state_matches = (
                exact_present and not altered_present and not unexpected_present
            )
        elif status == "rolled_back":
            expected_state = "absent"
            trigger_state_matches = (
                not exact_present
                and not altered_present
                and not unexpected_present
            )
        else:
            expected_state = "indeterminate_prepared"
            trigger_state_matches = False
        manifest_context = {
            "provided": True,
            "matches": database_matches and trigger_state_matches,
            "database_matches": database_matches,
            "expected_trigger_name": trigger_name,
            "expected_state": expected_state,
            "exact_trigger_state_matches": trigger_state_matches,
        }
        planned_value = manifest.get("observed_codex_version")
        planned_version = (
            str(planned_value) if isinstance(planned_value, str) else None
        )
        if planned_version is not None and current_version is not None:
            comparison = "compared"
            mismatch = planned_version != current_version
        else:
            comparison = "unknown"
    result = {
        "schema_version": "codex-storage-doctor.verify.v1",
        "tool_version": __version__,
        "generated_at": utc_now(),
        "inspection": inspection.to_dict(reveal_paths=args.reveal_paths),
        "sample": sample.to_dict(),
        "version_context": {
            "comparison": comparison,
            "planned": planned_version,
            "observed_now": current_version,
            "mismatch": mismatch,
        },
        "manifest_context": manifest_context,
        "claim_boundary": (
            "This bounded observation does not measure every disk write or "
            "physical drive endurance."
        ),
    }
    _emit(
        result,
        json_output=args.json,
        output=args.output,
        text_output=_verify_text(result),
    )
    return (
        EXIT_PARTIAL
        if (
            inspection.status != "ok"
            or sample.status != "ok"
            or mismatch
            or not manifest_context["matches"]
        )
        else EXIT_OK
    )


def _rollback_text(result: Mapping[str, Any]) -> str:
    if not result.get("changed"):
        return "The doctor-owned trigger was already absent; no change was made."
    return "\n".join(
        (
            "Rollback completed after a fresh verified backup.",
            f"Removed trigger: {result['trigger_name']}",
            f"Pre-rollback backup: {result['backup_path']}",
            f"Rollback record: {result['record']}",
        )
    )


def _run_rollback(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.expanduser().resolve()
    manifest = read_json_object(manifest_path)
    result = rollback(
        manifest,
        args.confirm,
        manifest_path=manifest_path,
    )
    _emit(
        result,
        json_output=args.json,
        output=args.output,
        text_output=_rollback_text(result),
    )
    return EXIT_OK


def _safety_exit(error: SafetyGateError) -> int:
    message = str(error).lower()
    if any(
        phrase in message
        for phrase in (
            "schema",
            "plan digest",
            "plan confirmation",
            "identity changed",
            "changed since planning",
            "version changed",
            "trigger sql fingerprint",
        )
    ):
        return EXIT_STALE_OR_SCHEMA
    if any(
        phrase in message
        for phrase in (
            "backup",
            "artifact",
            "free space",
            "manifest digest",
            "manifest schema",
        )
    ):
        return EXIT_ARTIFACT
    if "sqlite refused" in message or "quick_check" in message:
        return EXIT_SQLITE
    return EXIT_SAFETY_REFUSED


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["audit"]
    parser = build_parser()
    try:
        args = parser.parse_args(arguments)
        if args.command is None:
            parser.print_help()
            return EXIT_USAGE
        handlers = {
            "audit": _run_audit,
            "plan": _run_plan,
            "apply": _run_apply,
            "verify": _run_verify,
            "rollback": _run_rollback,
        }
        return handlers[args.command](args)
    except (CrossBoundaryError, SafetyBoundaryError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        return EXIT_SAFETY_REFUSED
    except PlanError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return EXIT_STALE_OR_SCHEMA
    except SafetyGateError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return _safety_exit(error)
    except sqlite3.Error as error:
        print(f"SQLite operation failed: {error}", file=sys.stderr)
        return EXIT_SQLITE
    except ArtifactReadError as error:
        print(f"Artifact operation failed: {error}", file=sys.stderr)
        return EXIT_ARTIFACT
    except (FileNotFoundError, ValueError) as error:
        print(f"Input error: {error}", file=sys.stderr)
        return EXIT_NOT_FOUND
    except OSError as error:
        print(f"Artifact operation failed: {error}", file=sys.stderr)
        return EXIT_ARTIFACT


if __name__ == "__main__":
    raise SystemExit(main())
