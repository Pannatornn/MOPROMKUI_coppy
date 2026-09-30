from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.safety import find_red_flags  # noqa: E402


CORPUS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "triage_cases.json"


def percentage(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def main() -> int:
    cases = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    tp = fp = tn = fn = 0
    errors: list[str] = []

    for case in cases:
        matches = find_red_flags(case["text"])
        detected = bool(matches)
        expected = case["level"] == "emergency"
        codes = {item["code"] for item in matches}

        if expected and detected:
            tp += 1
            expected_code = case.get("expected_code")
            if expected_code and expected_code not in codes:
                errors.append(
                    f'{case["id"]}: พบ Emergency แต่ได้ {sorted(codes)} แทน {expected_code}'
                )
        elif expected:
            fn += 1
            errors.append(f'{case["id"]}: FALSE NEGATIVE — {case["text"]}')
        elif detected:
            fp += 1
            errors.append(f'{case["id"]}: FALSE POSITIVE {sorted(codes)} — {case["text"]}')
        else:
            tn += 1

    print(f"Corpus: {len(cases)} cases (Emergency {tp + fn}, Not emergency {tn + fp})")
    print(f"TP={tp}  FN={fn}  FP={fp}  TN={tn}")
    print(f"Emergency recall: {percentage(tp, tp + fn):.1f}%")
    print(f"Emergency precision: {percentage(tp, tp + fp):.1f}%")
    print(f"Specificity: {percentage(tn, tn + fp):.1f}%")

    if errors:
        print("\nCases requiring review:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Result: PASS — no error in the maintained regression corpus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
