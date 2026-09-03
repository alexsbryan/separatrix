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
from pathlib import Path

from .cases import harvest
from .journal import Provenance, Run
from .study import load_study
from .sweep import DEFAULT_RESOLVE_TO, bracket_from_records, sweep
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
    if summary["served_mixed"]:
        mix = ", ".join(f"{m} x{n}" for m, n in
                        sorted(summary["served_counts"].items(), key=lambda kv: -kv[1]))
        print(f"          MIXED — the calls were answered by: {mix}")
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
    if summary["served_mixed"]:
        print(f"\nWARNING: more than one model answered this run, so its numbers "
              f"are a mixture and the banner above names only the first. See "
              f"`served` above for the counts.", file=sys.stderr)
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

    # The bar the run was JUDGED against, not the library default. A study that
    # declared `resolve_to = 0.1` and is re-derived at 0.25 gets a verdict nobody
    # ran, which is the same class of error as re-deriving against the wrong
    # threshold. Older journals predate the field and fall back to the default.
    resolve_to = args.resolve_to
    if resolve_to is None:
        resolve_to = (run.header.get("asking") or {}).get("resolve_to")
    if resolve_to is None and recorded is not None:
        resolve_to = recorded.get("resolve_to")
    if resolve_to is None:
        resolve_to = DEFAULT_RESOLVE_TO

    derived = bracket_from_records(run.other, threshold=threshold,
                                   name=args.name or "outcome",
                                   resolve_to=float(resolve_to))
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


def _probed(study, override: str | None):
    """The study's judge, paired with what a probe found out about it.

    One resolution path for both verbs, so `sep probe` cannot report a judge
    that `sep run` would not use. Having no cases is not the same as passing:
    it leaves the judge NEVER_RAN and unusable, which is the honest state for an
    instrument nobody has checked.
    """
    cases = study.cases(override)
    return study.judge if cases is None else probe(study.judge, cases)


def _render_validation(judge) -> None:
    v = judge.validation()
    print(f"judge     {judge.id}  tier={v.tier.value}  {v.verdict}  — {v.note}")
    if (bias := v.bias) is None:
        return
    for arm, row in sorted(bias.arms.items()):
        print(f"  {arm:<14} n={row['n']:>3}  errors={row['errors']:>3}  "
              f"rate={row['error_rate']:>5.0%}")
    if bias.p_value is not None:
        print(f"  {'asymmetry':<14} {bias.asymmetry:.0%}  "
              f"p={bias.p_value:.4g}  alpha={bias.alpha:g}")
    if v.discrimination is not None:
        print(f"  {'discrimination':<14} {v.discrimination:.3g}")


def _cmd_probe(args) -> int:
    """Ask whether the instrument is fair, and spend nothing else.

    Separate from `run` because the answer is worth having on its own: a reader
    that is worse at one end of the coordinate is a finding about the reader,
    and you want it before you have a study's worth of calls invested in it.
    """
    study = load_study(args.study)
    print(f"study     {study.name}   ({study.path.name})")
    if study.cases(args.cases) is None:
        print("this study declares no labelled cases, so there is nothing to "
              "probe with. Declare a [cases] table and `sep harvest` it, or "
              "point `cases` at a module:fn", file=sys.stderr)
        return 2
    judge = _probed(study, args.cases)
    _render_validation(judge)
    v = judge.validation()
    if args.json:
        print(json.dumps(v.as_row(), indent=2))
    return 0 if v.usable() else 3


def _cmd_harvest(args) -> int:
    """Ask both arms the probes, and write what came back for somebody to label.

    The one step in using this library that cannot be automated is deciding what
    a reply actually did, and that is correct — it is the ground truth every
    other number rests on. What CAN be automated is getting the replies, keeping
    the distinct ones, and putting them somewhere a reviewer can argue with.
    """
    study = load_study(args.study)
    source = study.case_source
    if source is None:
        print(f"{study.path.name} declares no [cases] table, so there is nothing "
              f"to harvest from. It needs `arms`, `probes`, and where to write.",
              file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else source.path
    draws = args.draws or source.draws
    probes = source.situations(study.config)
    print(f"study     {study.name}   ({study.path.name})")
    print(f"harvest   {len(source.arms)} arms x {len(probes)} probes x {draws} draws "
          f"= {len(source.arms) * len(probes) * draws} calls  -> {out.name}")
    try:
        result = harvest(study.chat, arms=source.arms, probes=source.probes,
                         draws=draws, path=out, config=study.config,
                         workers=study.workers,
                         on_probe=lambda arm, probe, n: print(
                             f"  {arm:<12} x{n}  {probe.prompt.splitlines()[-1][:56]}",
                             flush=True))
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"\n{result['distinct']} distinct replies from {result['asked']} calls")
    if result["truncated"]:
        print(f"{result['truncated']} dropped: cut off at max_tokens, so they "
              f"neither answered nor declined")
    for arm, n in sorted(result["per_arm"].items()):
        print(f"  {arm:<14} {n}")
    print(f"\nEvery row needs an `expected` of \"passed\" or \"failed\" before it "
          f"can probe anything.\nThat judgement is the ground truth and it is "
          f"yours to make.")
    return 0


def _cmd_run(args) -> int:
    study = load_study(args.study)
    print(f"study     {study.name}   ({study.path.name})")

    # The instrument, before the result. A study that cannot probe its judge
    # does not get to spend anything.
    judge = _probed(study, args.cases)
    _render_validation(judge)
    if not judge.validation().usable():
        print("\nrefusing to spend: probe the judge first "
              "(declare `cases` in the study, or pass --cases module:fn)",
              file=sys.stderr)
        return 3

    served = (Provenance.modelless().served if not study.chat.model
              else study.chat.probe_served())
    print(f"endpoint  {study.chat.base_url}  asked={study.chat.model or '(none)'}  "
          f"served={served}")
    if (reader := getattr(judge, "chat", None)) is not None and reader.model != study.chat.model:
        print(f"reader    {reader.base_url}  asked={reader.model}")

    with study.journal(served, judge) as journal:
        # A model judge records what it asked and what came back; a fold has
        # nothing to add and implements this empty. Guarded because a judge from
        # outside this library may predate the method.
        if callable(attach := getattr(judge, "attach", None)):
            attach(journal)
        arena = study.arena_factory(study=study, journal=journal)
        if study.coordinate is None:
            rulings = arena.run(dict(study.config), judge)
            for r in rulings:
                journal.ruling(r)
            print(f"\n{len(rulings)} rulings -> {Run.load(study.journal_path).verdict()}")
            return 0

        bracket = sweep(arena, judge, study.coordinate, study.outcome,
                        budget=study.budget, replicates=study.replicates,
                        paired=study.paired, resolve_to=study.resolve_to,
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
    bracket.add_argument("--resolve-to", dest="resolve_to", type=float,
                         help="fraction of the range a bracket must reach to count as "
                              "located (default: what the run declared)")
    bracket.add_argument("--json", action="store_true")
    bracket.set_defaults(fn=_cmd_bracket)

    run = subs.add_parser("run", help="run a study from a TOML file")
    run.add_argument("study")
    run.add_argument("--cases", help="module:fn giving labelled cases for the bias "
                                     "probe (default: what the study declares)")
    run.set_defaults(fn=_cmd_run)

    hrv = subs.add_parser("harvest", help="collect replies from both arms, to label")
    hrv.add_argument("study")
    hrv.add_argument("--out", help="where to write them (default: what [cases] says)")
    hrv.add_argument("--draws", type=int, help="replies per arm per probe")
    hrv.set_defaults(fn=_cmd_harvest)

    prb = subs.add_parser("probe", help="probe a study's judge and spend nothing else")
    prb.add_argument("study")
    prb.add_argument("--cases", help="module:fn giving labelled cases (default: what "
                                     "the study declares)")
    prb.add_argument("--json", action="store_true")
    prb.set_defaults(fn=_cmd_probe)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
