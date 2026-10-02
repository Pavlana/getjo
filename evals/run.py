"""Score the hand-labelled cases and compare Claude's verdicts with yours.

Run: python -m evals.run
"""

import json
import logging
import sys
from pathlib import Path

from core import config, store
from core.config import ConfigError
from jobs.score import load_cv, score_with_retry

CASES_PATH = Path("evals/cases/scoring.jsonl")
LABELS = ("apply", "maybe", "skip")
SKIP_MAX = 3  # a score of 3 or lower counts as "skip"
SWEEP = range(5, 10)  # thresholds to compare on the same scores


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    if not path.exists():
        raise ConfigError(f"{path} not found — see evals/cases/scoring.example.jsonl for the format")
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for n, case in enumerate(cases, 1):
        if case.get("expected") not in LABELS:
            raise ConfigError(f"{path} line {n}: expected must be one of {LABELS}, got {case.get('expected')!r}")
    return cases


def to_label(score: int | None, threshold: int) -> str:
    """Turn a score into the verdict radar.py would act on."""
    if score is None:
        return "unscored"
    if score >= threshold:
        return "apply"
    if score <= SKIP_MAX:
        return "skip"
    return "maybe"


def summarize(results: list[dict]) -> dict[str, tuple[int, int]]:
    """Each metric is (hits, out of), so small sets can't hide behind a percentage."""
    predicted_apply = [r for r in results if r["predicted"] == "apply"]
    expected_apply = [r for r in results if r["expected"] == "apply"]
    return {
        "agreement": (sum(r["expected"] == r["predicted"] for r in results), len(results)),
        "apply_precision": (sum(r["expected"] == "apply" for r in predicted_apply), len(predicted_apply)),
        "apply_recall": (sum(r["predicted"] == "apply" for r in expected_apply), len(expected_apply)),
    }


def sweep(results: list[dict], thresholds: range = SWEEP) -> list[tuple[int, tuple[int, int], tuple[int, int]]]:
    """For each threshold: (threshold, apply precision, apply recall) from the scores already in results.

    Unscored cases are never sent, whatever the threshold.
    """
    rows = []
    for threshold in thresholds:
        relabelled = [
            {"expected": r["expected"], "predicted": "apply" if (r["score"] or 0) >= threshold else "other"}
            for r in results
        ]
        metrics = summarize(relabelled)
        rows.append((threshold, metrics["apply_precision"], metrics["apply_recall"]))
    return rows


def _fraction(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits / total:.0%})" if total else "0/0 (n/a)"


def _claude_note(result: dict | None) -> str:
    if result is None:
        return "(no usable reply after two tries)"
    if result["dealbreakers"]:
        first = result["dealbreakers"][0]
        return f"dealbreaker: {first['rule']} — \"{first['quote']}\""
    if result["red_flags"]:
        return f"red flag: {result['red_flags'][0]}"
    if result["reasons"]:
        return f"reason: {result['reasons'][0]}"
    return "(no reasons or red flags given)"


def score_cases(cases: list[dict], scoring_cfg: dict, api_key: str) -> tuple[list[dict], float]:
    """Score every case with the production prompt. Reads the database, never writes to it."""
    conn = store.connect()
    cv_text = load_cv()
    results, cost = [], 0.0
    try:
        for case in cases:
            job = store.get_job(conn, case["job_id"])
            if job is None:
                raise ConfigError(f"case {case['job_id']} is not in data/jobs.db")
            result, completions = score_with_retry(
                job, cv_text, scoring_cfg["rubric"], scoring_cfg.get("dealbreakers", []),
                model=scoring_cfg["model"], api_key=api_key,
            )
            cost += sum(c.cost or 0 for c in completions)
            score = result["score"] if result else None
            results.append({
                **case,
                "score": score,
                "raw_score": result["raw_score"] if result else None,
                "predicted": to_label(score, scoring_cfg["notify_threshold"]),
                "claude_note": _claude_note(result),
            })
    finally:
        conn.close()
    return results, cost


def report(results: list[dict], cost: float, scoring_cfg: dict) -> str:
    metrics = summarize(results)
    lines = [
        f"Eval: {len(results)} cases · model {scoring_cfg['model']} · apply at score >= "
        f"{scoring_cfg['notify_threshold']}, skip at <= {SKIP_MAX} · "
        f"{len(scoring_cfg.get('dealbreakers', []))} dealbreakers",
        f"Agreement:        {_fraction(*metrics['agreement'])}",
        f"Apply precision:  {_fraction(*metrics['apply_precision'])}   of jobs Claude would send, you'd apply to",
        f"Apply recall:     {_fraction(*metrics['apply_recall'])}   of jobs you'd apply to, Claude would send",
        f"Cost:             ${cost:.4f}",
    ]

    apply_scores = sorted((r["score"] for r in results if r["expected"] == "apply"), key=lambda s: (s is None, s))
    lines += ["", "Scores of jobs you'd apply to: " + ", ".join("-" if s is None else str(s) for s in apply_scores)]
    lines += ["", "Threshold sweep (same scores; apply at score >= T):", "  T    sent  precision     recall"]
    for threshold, precision, recall in sweep(results):
        marker = "*" if threshold == scoring_cfg["notify_threshold"] else " "
        lines.append(f"  {threshold}{marker}  {precision[1]:>4}  {_fraction(*precision):<12}  {_fraction(*recall)}")
    disagreements = [r for r in results if r["expected"] != r["predicted"]]
    if disagreements:
        lines += ["", f"Disagreements ({len(disagreements)}):"]
        for r in disagreements:
            if r["score"] is None:
                score = "-"
            elif r["raw_score"] != r["score"]:
                score = f"{r['score']}, capped from {r['raw_score']}"
            else:
                score = r["score"]
            lines.append(f"  you: {r['expected']:<5}  Claude: {r['predicted']} ({score})  {r['title']} — {r['company']}")
            if r.get("reason"):
                lines.append(f"      your reason: {r['reason']}")
            lines.append(f"      Claude's {r['claude_note']}")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="%(levelname)s %(name)s: %(message)s")
    scoring_cfg = config.load_config()["profile"]["scoring"]
    api_key = config.require_env(["ANTHROPIC_API_KEY"])["ANTHROPIC_API_KEY"]
    results, cost = score_cases(load_cases(), scoring_cfg, api_key)
    print(report(results, cost, scoring_cfg))


if __name__ == "__main__":
    main()
