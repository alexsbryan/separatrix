# SPDX-License-Identifier: AGPL-3.0-or-later
"""`sep` — the command line.

Every verb here is a fold over a journal. None of them opens a socket or loads a
model, and that is the property worth protecting: if re-deriving a published
number needed the thing that produced it, nobody could check it.
"""
from __future__ import annotations

import argparse
import json
import sys

from .journal import Run
from .sweep import bracket_from_records

__all__ = ["main"]


def _cmd_replay(args) -> int:
    run = Run.load(args.journal)
    summary = run.summary()
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0 if run.verdict().is_pass() else 1

    print(f"run       {summary['run'] or '(no header)'}")
    print(f"served    {summary['served']}")
    if summary["endpoint"]:
        print(f"endpoint  {summary['endpoint']}")
    if summary["judge"]:
        print(f"judge     {summary['judge']}")
    print(f"rulings   {summary['rulings']}   cached responses {summary['responses_cached']}")
    for verdict, n in sorted(summary["counts"].items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:16} {n}")
    print(f"verdict   {summary['verdict'].upper().replace('_', '-')}")

    if summary["unjudged"]:
        print(f"\n{summary['unjudged']} ruling(s) reached no verdict:")
        seen = {}
        for r in run.unjudged():
            seen[r.get("note", "(no reason given)")] = seen.get(r.get("note", ""), 0) + 1
        for note, n in sorted(seen.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {n:4}x {note}")
    if summary["served"] == "UNRECORDED":
        print("\nWARNING: this journal records no served model. Its numbers name "
              "nothing and cannot be reproduced.", file=sys.stderr)
    return 0 if run.verdict().is_pass() else 1


def _cmd_bracket(args) -> int:
    run = Run.load(args.journal)
    recorded = next((r for r in run.other if r.get("t") == "bracket"), None)
    threshold = args.threshold
    if threshold is None:
        if recorded is None or recorded.get("threshold") is None:
            print("this journal records no bracket, so pass --threshold to say what "
                  "line the outcome had to cross", file=sys.stderr)
            return 2
        threshold = float(recorded["threshold"])

    derived = bracket_from_records(run.other, threshold=threshold,
                                   name=args.name or "outcome")
    if args.json:
        print(json.dumps(derived.as_row(), indent=2))
    else:
        print(derived.render())

    if recorded is None:
        return 0 if derived.verdict.is_pass() else 1

    # The point of re-derivation: a recorded result that its own evidence does
    # not reproduce is the finding, not a rounding difference to smooth over.
    same = (recorded["verdict"] == derived.verdict.value
            and recorded["lo"] == derived.lo and recorded["hi"] == derived.hi)
    if not same:
        print(f"\nMISMATCH — the journal records "
              f"{recorded['verdict']} [{recorded['lo']:g}, {recorded['hi']:g}] but its "
              f"own samples re-derive {derived.verdict.value} "
              f"[{derived.lo:g}, {derived.hi:g}]", file=sys.stderr)
        return 2
    print("\nre-derived from the journal's own samples; matches what was recorded")
    return 0 if derived.verdict.is_pass() else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sep", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = ap.add_subparsers(dest="cmd", required=True)

    replay = subs.add_parser("replay", help="re-derive a run from its journal (no model)")
    replay.add_argument("journal")
    replay.add_argument("--json", action="store_true", help="machine-readable output")
    replay.set_defaults(fn=_cmd_replay)

    bracket = subs.add_parser("bracket", help="re-derive a bracket from journalled samples (no model)")
    bracket.add_argument("journal")
    bracket.add_argument("--threshold", type=float, help="the line the outcome had to cross")
    bracket.add_argument("--name", help="outcome name, for the rendering")
    bracket.add_argument("--json", action="store_true")
    bracket.set_defaults(fn=_cmd_bracket)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
