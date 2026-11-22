"""The report of a run: one file, numbers only.

It names the agent and its version, the prompt version, the model alias
and the models the gateway reported, and the date. It holds the scores of
the model and of the rules, what a message cost, and why messages went
unanswered. No id, no label of a single message, nothing of a mail, so a
report can be versioned beside the change it measures. A label or field
name the agent does not declare as its own, such as the name of a group
of sorting, is replaced by ``label-<n>`` or ``field-<n>``. See
docs/mailbox-agents/concept/evaluation.md.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ..contract import Agent
from .scoring import Outcome, Scores, score

__all__ = ["build", "render", "write"]


def _ratio(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _placeholders(
    declared: frozenset[str], names: set[str], prefix: str
) -> dict[str, str]:
    """Each name as the report shows it: a declared one as it is, any other
    as ``<prefix>-<n>``, numbered in the sorted order of the names."""
    others = sorted(names - declared)
    shown = {name: f"{prefix}-{n}" for n, name in enumerate(others, start=1)}
    return {name: shown.get(name, name) for name in names}


def _scores(
    scores: Scores, labels: dict[str, str], fields: dict[str, str]
) -> dict[str, Any]:
    return {
        "messages": scores.messages,
        "agreed": scores.agreed,
        "accuracy": _ratio(scores.accuracy),
        "unanswered": scores.unanswered,
        "refused": scores.refused,
        "labels": {
            labels[name]: {
                "true_positive": s.true_positive,
                "false_positive": s.false_positive,
                "false_negative": s.false_negative,
                "precision": _ratio(s.precision),
                "recall": _ratio(s.recall),
            }
            for name, s in sorted(scores.labels.items(), key=lambda i: labels[i[0]])
        },
        "fields": {
            fields[name]: {
                "right": f.right,
                "wrong": f.wrong,
                "missing": f.missing,
                "invented": f.invented,
                "empty": f.empty,
            }
            for name, f in sorted(scores.fields.items(), key=lambda i: fields[i[0]])
        },
    }


def build(
    agent: Agent,
    model_alias: str,
    outcomes: list[Outcome],
    when: datetime,
) -> dict[str, Any]:
    model, rules = score(outcomes)
    labels = _placeholders(
        agent.report_labels, set(model.labels) | set(rules.labels), "label"
    )
    fields = _placeholders(
        agent.report_fields, set(model.fields) | set(rules.fields), "field"
    )
    count = len(outcomes) or 1
    return {
        "agent": agent.name,
        "agent_version": agent.version,
        "prompt_version": agent.prompt_version,
        "model_alias": model_alias,
        "models_reported": sorted({m for o in outcomes for m in o.models}),
        "date": when.date().isoformat(),
        "gold_messages": len(outcomes),
        "model": _scores(model, labels, fields),
        "baseline": _scores(rules, labels, fields),
        "per_message": {
            "tokens_in": round(sum(o.tokens_in for o in outcomes) / count, 1),
            "tokens_out": round(sum(o.tokens_out for o in outcomes) / count, 1),
            "seconds": round(sum(o.duration_ms for o in outcomes) / count / 1000, 3),
        },
        "unanswered_because": dict(
            sorted(Counter(o.failure for o in outcomes if o.failure).items())
        ),
    }


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", text).strip("-") or "none"


def write(report: dict[str, Any], folder: Path) -> Path:
    """Write ``report`` to ``folder/<agent>/``, named by date, versions and
    model alias. A second run on the same day replaces the first."""
    name = "-".join(
        _slug(part)
        for part in (
            report["date"],
            f"v{report['agent_version']}",
            report["prompt_version"] or "no-prompt",
            report["model_alias"] or "no-model",
        )
    )
    path = folder / report["agent"] / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    return path


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f} %"


def render(report: dict[str, Any]) -> list[str]:
    """The report as lines for a terminal, the model beside the rules."""
    model, rules = report["model"], report["baseline"]
    lines = [
        f"{report['agent']} {report['agent_version']}, prompt "
        f"{report['prompt_version'] or '-'}, model {report['model_alias'] or '-'}"
        f" ({', '.join(report['models_reported']) or 'none reported'}), "
        f"{report['gold_messages']} messages",
        f"  accuracy: model {_percent(model['accuracy'])}, "
        f"rules {_percent(rules['accuracy'])}",
    ]
    for label in sorted(set(model["labels"]) | set(rules["labels"])):
        m = model["labels"].get(label, {})
        r = rules["labels"].get(label, {})
        lines.append(
            f"  {label}: precision {_percent(m.get('precision'))} / "
            f"{_percent(r.get('precision'))}, recall {_percent(m.get('recall'))} / "
            f"{_percent(r.get('recall'))}  (model / rules)"
        )
    for name, f in model["fields"].items():
        lines.append(
            f"  field {name}: right {f['right']}, wrong {f['wrong']}, missing "
            f"{f['missing']}, invented {f['invented']}, empty {f['empty']}"
        )
    cost = report["per_message"]
    lines.append(
        f"  per message: {cost['tokens_in']} tokens in, {cost['tokens_out']} out, "
        f"{cost['seconds']} s"
    )
    if report["unanswered_because"]:
        why = ", ".join(f"{k} {v}" for k, v in report["unanswered_because"].items())
        lines.append(f"  unanswered: {why}")
    return lines
