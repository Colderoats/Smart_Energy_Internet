"""Prints the Stop-event -> fault / not-fault mapping actually applied
(ai/taxonomy.py) with per-message event counts, for review.

    venv\\Scripts\\python -m ai.print_taxonomy
"""

from collections import Counter, defaultdict

from ai import dataset as D


def main() -> None:
    rows = defaultdict(lambda: [0, ""])
    for n in D.TURBINES:
        for e in D._load_stop_events(D.DATA_DIR, n):
            key = (e.is_fault, e.iec_category or "(blank)", e.message)
            rows[key][0] += 1
    totals = Counter()
    for (is_fault, iec, msg), (count, _) in sorted(rows.items(), key=lambda kv: (-kv[0][0], kv[0][1], -kv[1][0])):
        totals[is_fault] += count
        print(f"{'FAULT ' if is_fault else 'masked'}  {count:4d}  [{iec}]  {msg}")
    print(f"\ngenuine-fault events: {totals[True]}   masked (planned/routine/external) events: {totals[False]}")


if __name__ == "__main__":
    main()
