# SPDX-License-Identifier: AGPL-3.0-or-later
"""Labelled cases: harvest replies from both arms, label them, keep the file.

The bias probe is the load-bearing check in this library and it is only as good
as what it is fed. Cases invented at a keyboard are easy in a particular way —
they are what the author already believes the two arms sound like — and a judge
that passes on them has been asked nothing. The first probe of this project's
own model judge scored 40/40 on hand-written cases and established very little.

So: **the cases come from the arms.** Take the two dispositions the coordinate
actually produces, ask them the probes where the judgement is hard, and label
what comes back. Then a probe is a claim about replies this study will really
see, the labelled file is in the repository where anyone can disagree with a
specific line, and re-probing after a prompt change costs nothing.

Harvesting deliberately does NOT go through `Responder`. Its cache exists to
avoid paying twice for the same question, and here paying again is the entire
point: what varies between draws is the variety a judge has to cope with.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .client import Chat
from .judge import LabeledCase
from .trial import Situation, exchange
from .verdict import Verdict

__all__ = ["harvest", "labelled", "counts", "arm_spec", "LABELS"]

LABELS = {"passed": Verdict.PASSED, "failed": Verdict.FAILED}


def _render(situation: Situation) -> str:
    return (situation.prompt if not situation.evidence else
            "\n".join([*[f"- {e}" for e in situation.evidence], "", situation.prompt]))


def arm_spec(value: Any) -> dict:
    """What defines an end of the coordinate. Two shapes, because there are two.

    Where the coordinate acts through SELECTION — a reward structure breeding
    one disposition or another — an arm is a genome, and the bare string form
    says so. Where it acts through the SITUATION — a payoff matrix an agent is
    shown, a regeneration rate in the prompt — an arm is a config, and the same
    genome faces two different worlds. A study may need both at once.
    """
    if isinstance(value, str):
        return {"genome": value, "config": {}}
    return {"genome": value.get("genome", ""), "config": dict(value.get("config", {}))}


def harvest(chat: Chat, *, arms: Mapping[str, Any], probes: Any, draws: int,
            path: str | Path, config: Mapping[str, Any] | None = None,
            workers: int = 1,
            on_probe: Callable[[str, Situation, int], None] | None = None) -> dict:
    """Ask each arm each probe `draws` times; write the DISTINCT replies.

    Distinct, because a model that says the same sentence nine times would
    otherwise weight that sentence nine times in a probe, and the probe would be
    measuring the model's favourite phrasing rather than the judge's fairness.
    The count of draws behind each row is kept, so the collapse is visible.
    """
    path = Path(path)
    if path.exists():
        raise FileExistsError(
            f"{path} already exists and may carry labels somebody wrote by hand. "
            f"Delete it deliberately, or harvest to a different --out.")

    base = dict(config or {})
    seen: dict[tuple[str, str, str], dict] = {}
    for arm, spec in ((name, arm_spec(v)) for name, v in arms.items()):
        genome, at = spec["genome"], {**base, **spec["config"]}
        situations = probes(at) if callable(probes) else probes
        for probe in situations:
            if on_probe:
                on_probe(arm, probe, draws)
            # Deliberately NOT through `Responder`: its cache exists to avoid
            # paying twice for one question, and here paying again is the point.
            # Concurrent, because the draws do not depend on each other.
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                completions = list(pool.map(
                    lambda _: chat.complete(genome, _render(probe)), range(draws)))
            for completion in completions:
                text = completion.text.strip()
                key = (arm, probe.id, text)
                if key in seen:
                    seen[key]["draws"] += 1
                    continue
                seen[key] = {"arm": arm, "genome": genome, "config": at,
                             "prompt": probe.prompt,
                             "evidence": list(probe.evidence), "kind": probe.kind,
                             "text": text, "served": completion.served,
                             "finish": completion.finish, "draws": 1,
                             # The one field a person fills in. Null is not a
                             # label and `labelled` refuses to guess at it.
                             "expected": None}

    # A reply the server cut at the token limit is not a case anybody can label:
    # it neither answered nor declined, and the judges refuse it structurally
    # (`judge.cut_off`) rather than by anyone's reading. Dropped here, and
    # COUNTED — a harvest that is mostly truncation is a `max_tokens` problem
    # and the number is how you find that out.
    kept = [r for r in seen.values() if r["finish"] != "length"]
    dropped = len(seen) - len(kept)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    per_arm: dict[str, int] = {}
    for row in kept:
        per_arm[row["arm"]] = per_arm.get(row["arm"], 0) + 1
    asked = sum(len(probes(a["config"]) if callable(probes) else probes) * draws
                for a in (arm_spec(v) for v in arms.values()))
    return {"path": str(path), "distinct": len(kept), "per_arm": per_arm,
            "asked": asked, "truncated": dropped}


def labelled(path: str | Path) -> list[LabeledCase]:
    """Read a harvested file back as probe cases, or say what is missing.

    An unlabelled row is not a case with an unknown answer to be skipped
    quietly: it is work somebody has not done, and a probe run on the labelled
    half of a file is a probe on whichever half was easy to decide.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist. Harvest replies from both arms first "
            f"(`sep harvest <study.toml>`), then label each row's `expected`.")

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    unlabelled = [i for i, r in enumerate(rows, 1) if r.get("expected") not in LABELS]
    if unlabelled:
        raise ValueError(
            f"{path}: {len(unlabelled)} of {len(rows)} rows have no `expected` "
            f"({', '.join(str(i) for i in unlabelled[:8])}"
            f"{', …' if len(unlabelled) > 8 else ''}). "
            f"Label every row {sorted(LABELS)} — a probe on the rows that were "
            f"easy to label is a probe on nothing.")

    # The arm's config travels with the case. Without it, a judge that reads the
    # configuration a trial happened under is probed against its own defaults
    # rather than against the two ends of the coordinate — which is a probe of
    # something nobody asked about.
    return [LabeledCase(exchange(r["prompt"], r["text"], evidence=r.get("evidence", ()),
                                 kind=r.get("kind", "unspecified"),
                                 meta=r.get("config") or {}),
                        LABELS[r["expected"]], arm=r["arm"])
            for r in rows]


def counts(path: str | Path) -> dict:
    """Rows per arm per label, for looking at a file before probing with it.

    A probe needs both classes present in both arms or it is measuring
    something narrower than it claims, and that is easier to see as a table than
    to discover from a COULD_NOT_JUDGE afterwards.
    """
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        label = r.get("expected") or "unlabelled"
        out.setdefault(r["arm"], {})[label] = out.setdefault(r["arm"], {}).get(label, 0) + 1
    return out


def rows_from(cases: Iterable[LabeledCase]) -> list[dict[str, Any]]:
    """Cases back to rows, for a file somebody wants to inspect or re-label."""
    return [{"arm": c.arm, "expected": c.expected.value, **dict(c.trial.facts())}
            for c in cases]
