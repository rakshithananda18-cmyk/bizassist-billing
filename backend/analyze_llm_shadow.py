"""
analyze_llm_shadow.py — report card for the LLM router shadow (NEW system).
============================================================================
Reads the backend log for '[ROUTER][llm-shadow]' lines (emitted when
LLM_ROUTER=shadow) and summarizes cutover-readiness.

Buckets:
  AGREE         both routers behaved the same — boring, good.
  MODE-UPGRADE  the LLM router found 'advise' or 'act' where legacy could only
                return raw data / hallucinate — these are the loyalty-offers and
                'Escalate → Done.' bug classes the legacy stack CANNOT express.
                Review them: they're usually wins, not errors.
  DISAGREE      genuinely different routing — hand-label who was right.
  ERROR         the LLM call failed (legacy answered as always).

Usage (from backend/):
    python analyze_llm_shadow.py                      # reads logs/bizassist.log
    python analyze_llm_shadow.py path/to/other.log
    python analyze_llm_shadow.py --top 30
"""
import re
import sys
from collections import Counter

_LINE = re.compile(
    r"\[ROUTER\]\[llm-shadow\]\s+(?P<verdict>AGREE|DISAGREE|MODE-UPGRADE|ERROR)\s+\|\s+"
    r"legacy=\((?P<legacy>[^)]*)\)\s+"
    r"llm=\((?P<llm>.*?)\)\s+\|\s+q='(?P<q>.*)'\s*$"
)


def parse(path):
    counts = Counter()
    rows = {"DISAGREE": [], "MODE-UPGRADE": [], "ERROR": []}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _LINE.search(line)
            if not m:
                continue
            v = m.group("verdict")
            counts[v] += 1
            if v in rows:
                rows[v].append((m.group("q"), m.group("legacy").strip(),
                                m.group("llm").strip()))
    return counts, rows


def main(argv):
    path, top = "logs/bizassist.log", 20
    args = list(argv)
    if "--top" in args:
        i = args.index("--top")
        top = int(args[i + 1])
        del args[i:i + 2]
    if args:
        path = args[0]

    try:
        counts, rows = parse(path)
    except FileNotFoundError:
        print(f"Log file not found: {path}")
        print("Set LOG_FILE=logs/bizassist.log and LLM_ROUTER=shadow, then send queries.")
        return 1

    total = sum(counts.values())
    if not total:
        print("No [ROUTER][llm-shadow] lines found.")
        print("Confirm LLM_ROUTER=shadow is set and send a few chat queries.")
        return 1

    print(f"\n=== LLM Router Shadow Report ({total} comparisons) ===\n")
    for v in ("AGREE", "MODE-UPGRADE", "DISAGREE", "ERROR"):
        pct = 100.0 * counts[v] / total
        print(f"  {v:<13} {counts[v]:>5}  ({pct:5.1f}%)")

    decided = counts["AGREE"] + counts["DISAGREE"]
    if decided:
        print(f"\n  Agreement on comparable routes: "
              f"{100.0 * counts['AGREE'] / decided:.1f}%  "
              f"(MODE-UPGRADEs excluded — legacy can't express them)")

    for bucket, title in (("MODE-UPGRADE", "Mode upgrades (likely wins — verify)"),
                          ("DISAGREE",     "Disagreements (hand-label these)"),
                          ("ERROR",        "LLM failures (legacy served as usual)")):
        items = rows[bucket]
        if not items:
            continue
        print(f"\n--- {title} — showing {min(top, len(items))} of {len(items)} ---")
        seen = Counter(q for q, *_ in items)
        shown = set()
        for q, legacy, llm in items:
            if q in shown:
                continue
            shown.add(q)
            n = f" (×{seen[q]})" if seen[q] > 1 else ""
            print(f"  q: {q}{n}")
            print(f"     legacy: {legacy}")
            print(f"     llm:    {llm}")
            if len(shown) >= top:
                break

    print("\nCutover guidance: flip when AGREE≥95% on comparable routes AND every "
          "DISAGREE has been hand-labelled with the LLM right ≥90% of the time.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
