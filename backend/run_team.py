"""Command line entry point for the Campus Customs agent team.

    python -m backend.run_team --reset                                    # restore the working DB only
    python -m backend.run_team --reset --all --approval interactive --approver-name "Philipp"
    python -m backend.run_team --ticket 101 --approval deny               # unattended: payments are refused
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.approvals import ConsoleApprover, DenyAllApprover
from backend.config import AUDIT_TRAIL_FILE, MODEL_NAME
from backend.team import reset_working_db, run_team


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the Campus Customs agent team (model: gpt-6-luna via Portkey).")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--ticket", type=int, action="append", help="Ticket id to resolve (repeatable).")
    target.add_argument("--all", action="store_true", help="Resolve every open ticket together.")
    p.add_argument("--reset", action="store_true", help="Copy data/campus_customs.db over the working copy first.")
    p.add_argument("--approval", choices=["interactive", "deny"], default="interactive",
                   help="interactive: a human approves at the console; deny: every gated action is refused.")
    p.add_argument("--approver-name", default="", help="Name of the human approver (required for interactive).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    if args.reset:
        print(f"Working database reset from the original (sha256 {reset_working_db()[:16]}...).")
    if not (args.ticket or args.all):
        return 0
    if args.approval == "interactive":
        name = args.approver_name or input("Human approver name: ")
        approver = ConsoleApprover(name)
    else:
        approver = DenyAllApprover()

    print(f"Running the team on {'all open tickets' if args.all else args.ticket} with {MODEL_NAME} ...")
    result = asyncio.run(run_team(None if args.all else args.ticket, approver))
    print(f"\nTeam run {result.team_run_id} finished: {result.stop_reason}")
    print(f"Usage: {result.usage}")
    print(f"Database changed: {result.db_sha256_before != result.db_sha256_after}")
    if result.report:
        print("\n" + result.report.model_dump_json(indent=2))
    print(f"\nAudit trail: {AUDIT_TRAIL_FILE}")
    return 0 if result.report else 1


if __name__ == "__main__":
    raise SystemExit(main())
