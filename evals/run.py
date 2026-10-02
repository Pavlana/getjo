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


def _fraction(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits / total:.0%})" if total else "0/0 (n/a)"


def _claude_note(result: dict | None) -> str:
    if result is None:
        return "(no usable reply after two tries)"
    if result["red_flags"]:
        return f"red flag: {result['red_flags'][0]}"
    return f"reason: {result['reasons'][0]}"


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
                job, cv_text, scoring_cfg["rubric"], model=scoring_cfg["model"], api_key=api_key
            )
            cost += sum(c.cost or 0 for c in completions)
            score = result["score"] if result else None
            results.append({
                **case,
                "score": score,
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
        f"{scoring_cfg['notify_threshold']}, skip at <= {SKIP_MAX}",
        f"Agreement:        {_fraction(*metrics['agreement'])}",
        f"Apply precision:  {_fraction(*metrics['apply_precision'])}   of jobs Claude would send, you'd apply to",
        f"Apply recall:     {_fraction(*metrics['apply_recall'])}   of jobs you'd apply to, Claude would send",
        f"Cost:             ${cost:.4f}",
    ]
    disagreements = [r for r in results if r["expected"] != r["predicted"]]
    if disagreements:
        lines += ["", f"Disagreements ({len(disagreements)}):"]
        for r in disagreements:
            score = "-" if r["score"] is None else r["score"]
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
