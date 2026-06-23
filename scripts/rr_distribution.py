#!/usr/bin/env python3
"""Diagnostic: R:R distribution across recent recommendations."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter
from data.db import Database


def main():
    db = Database()
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT setup_type, rr FROM recommendations WHERE rr > 0 ORDER BY rr"
    ).fetchall()

    if not rows:
        print("No recommendations found with rr > 0.")
        return

    rr_values = [r[1] for r in rows]
    setup_types = [r[0] for r in rows]
    total = len(rr_values)

    print(f"Recommendations with R:R > 0: {total}\n")

    # Histogram with 0.5x buckets
    max_rr = max(rr_values)
    bucket_size = 0.5
    print("Histogram (0.5x buckets):")
    print(f"{'Bucket':<10} {'Count':<8} {'Distribution'}")
    bucket = 0.0
    while bucket <= max_rr + bucket_size:
        upper = bucket + bucket_size
        count = sum(1 for r in rr_values if bucket <= r < upper)
        bar = "#" * count
        print(f"{bucket:.1f}-{upper:.1f}x  {count:<8} {bar}")
        bucket = upper

    # % at exactly common floor values
    print("\nPercentage at specific R:R values:")
    for floor_val in [2.0, 2.5, 3.0]:
        count = sum(1 for r in rr_values if abs(r - floor_val) < 0.01)
        pct = (count / total) * 100
        print(f"  Exactly {floor_val}x: {count}/{total} ({pct:.1f}%)")

    # By setup type
    print("\nBy setup type:")
    setup_groups = Counter(setup_types)
    seen = set()
    for st, rr in rows:
        if st not in seen:
            group_rr = [r for s, r in rows if s == st]
            avg = sum(group_rr) / len(group_rr)
            print(f"  {st:<20} count={len(group_rr):<4} avg_rr={avg:.2f}")
            seen.add(st)

    sys.exit(0)


if __name__ == '__main__':
    main()
