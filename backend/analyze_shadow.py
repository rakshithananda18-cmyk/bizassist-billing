"""
analyze_shadow.py — Phase 1 shadow-route report.
================================================
Reads the backend log and tallies the semantic-vs-regex router comparison that
INTENT_ROUTER=shadow emits, so you can judge cutover-readiness (Step 3) without
grepping by hand.

Usage (from backend/):
    python analyze_shadow.py                      # reads logs/bizassist.log
    python analyze_shadow.py path/to/other.log    # explicit file
    python analyze_shadow.py --top 30             # show more disagreements

Each shadow line looks like:
    [ROUTER][shadow] DISAGREE | regex=(AI_SIMPLE, handler=None, topic=expiring_soon) \
        semantic=(DIRECT, expiring_soon, 0.78) | q='namdhari fresh'
"""
import re
import sys
from collections import Counter

_LINE = re.compile(
    r"\[ROUTER\]\[shadow\]\s+(AGREE|DISAGREE)\s+\|\s+"
    r"regex=\((?P<regex>[^)]*)\)\s+"
    r"semantic=\((?P<sem>[^)]*)\)\s+\|\s+q='(?P<q>.*)'\s*$"
)


def parse(path):
    agree = 0
    disagree = []          # list of (query, regex, semantic)
    dis_q = Counter()      # most frequent disagreeing queries
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _LINE.search(line)
            if not m:
                continue
            if m.group(1) == "DISAGREE":
                q = m.group("q")
                disagree.append((q, m.group("regex").strip(), m.group("sem").strip()))
                dis_q[q] += 1
            else:
                agree += 1
    return agree, disagree, dis_q


def main(argv):
    path = "logs/bizassist.log"
    top = 20
    args = list(argv)
    if "--top" in args:
        i = args.index("--top")
        top = int(args[i + 1])
        del args[i:i + 2]
    if args:
        path = args[0]

    try:
        agree, disagree, dis_q = parse(path)
    except FileNotFoundError:
        print(f"Log file not found: {path}")
        print("Set LOG_FILE in backend/.env and restart the backend so it writes a log,")
        print("then use the app for a while to accumulate shadow comparisons.")
        return 1

    total = agree + len(disagree)
    if total == 0:
        print(f"No [ROUTER][shadow] lines in {path} yet.")
        print("Confirm INTENT_ROUTER=shadow is set and send a few chat queries.")
        return 0

    pct = 100.0 * agree / total
    print("=" * 66)
    print(f"Shadow-route report  ({path})")
    print("=" * 66)
    print(f"  total compared : {total}")
    print(f"  AGREE          : {agree}  ({pct:.1f}%)")
    print(f"  DISAGREE       : {len(disagree)}  ({100 - pct:.1f}%)")
    print(f"  cutover bar    : >= 95% agreement on real traffic")
    print(f"  status         : {'READY' if pct >= 95 else 'keep gathering / tune seeds'}")
    print()

    if disagree:
        print(f"Top {min(top, len(dis_q))} disagreeing queries (by frequency):")
        print("-" * 66)
        shown = {q for q, _ in dis_q.most_common(top)}
        seen = set()
        for q, count in dis_q.most_common(top):
            # show one representative regex/semantic pairing per query
            rep = next(d for d in disagree if d[0] == q)
            print(f"  x{count:<3} q='{q}'")
            print(f"        regex    = ({rep[1]})")
            print(f"        semantic = ({rep[2]})")
        print()
        print("Read each: would the semantic route have been BETTER or WORSE than")
        print("regex? Frequent WORSE cases => add/adjust seeds in intent_router.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
