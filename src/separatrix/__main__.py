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

from .journal import Provenance, Run
from .study import load_study, resolve
from .sweep import bracket_from_records, sweep
from .validate import probe

__all__ = ["main"]


def _several(path, chosen):
    ids = Run.runs(path)
    if len(ids) > 1:
        print(f"note      this journal holds {len(ids)} runs; showing "
              f"{chosen or ids[-1]} (--run to pick another)")


def _cmd_replay(args) -> int:
    _several(args.journal, args.run)
    run = Run.load(args.journal, args.run)
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
    if summary["kind"] == "sweep":
        print(f"samples   {summary['samples']}   cached responses "
              f"{summary['responses_cached']}")
        if b := summary["bracket"]:
            print(f"bracket   {b['coordinate']} in [{b['lo']:g}, {b['hi']:g}]  "
                  f"(width {b['width']:g}, noise {b['noise']:.4g})")
            print(f"          {b['note']}")
    else:
        print(f"rulings   {summary['rulings']}   cached responses "
              f"{summary['responses_cached']}")
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
    _several(args.journal, args.run)
    run = Run.load(args.journal, args.run)
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


def _cmd_run(args) -> int:
    study = load_study(args.study)
    print(f"study     {study.name}   ({study.path.name})")

    # The instrument, before the result. A study that cannot probe its judge
    # does not get to spend anything.
    cases = resolve(args.cases, root=study.path.parent) if args.cases else None
    judge = probe(study.judge, cases() if callable(cases) else (cases or [])) \
        if cases is not None else study.judge
    v = judge.validation()
    print(f"judge     {judge.id}  tier={v.tier.value}  {v.verdict}  — {v.note}")
    if not v.usable():
        print("\nrefusing to spend: probe the judge first "
              "(declare `cases` in the study, or pass --cases module:fn)",
              file=sys.stderr)
        return 3

    served = (Provenance.modelless().served if not study.chat.model
              else study.chat.probe_served())
    print(f"endpoint  {study.chat.base_url}  asked={study.chat.model or '(none)'}  "
          f"served={served}")

    with study.journal(served, judge) as journal:
        arena = study.arena_factory(study=study, journal=journal)
        if study.coordinate is None:
            rulings = arena.run(dict(study.config), judge)
            for r in rulings:
                journal.ruling(r)
            print(f"\n{len(rulings)} rulings -> {Run.load(study.journal_path).verdict()}")
            return 0

        bracket = sweep(arena, judge, study.coordinate, study.outcome,
                        budget=study.budget, replicates=study.replicates,
                        config=study.config, journal=journal,
                        on_forecast=lambda f: print(f"forecast  "
                                                    f"{f.render(study.coordinate)}"))
    print()
    print(bracket.render())
    print(f"\njournal   {study.journal_path}")
    return 0 if bracket.verdict.is_pass() else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sep", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = ap.add_subparsers(dest="cmd", required=True)

    replay = subs.add_parser("replay", help="re-derive a run from its journal (no model)")
    replay.add_argument("journal")
    replay.add_argument("--run", help="which run in the journal (default: the last)")
    replay.add_argument("--json", action="store_true", help="machine-readable output")
    replay.set_defaults(fn=_cmd_replay)

    bracket = subs.add_parser("bracket", help="re-derive a bracket from journalled samples (no model)")
    bracket.add_argument("journal")
    bracket.add_argument("--threshold", type=float, help="the line the outcome had to cross")
    bracket.add_argument("--name", help="outcome name, for the rendering")
    bracket.add_argument("--run", help="which run in the journal (default: the last)")
    bracket.add_argument("--json", action="store_true")
    bracket.set_defaults(fn=_cmd_bracket)

    run = subs.add_parser("run", help="run a study from a TOML file")
    run.add_argument("study")
    run.add_argument("--cases", help="module:fn giving labelled cases for the bias probe")
    run.set_defaults(fn=_cmd_run)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
