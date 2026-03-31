#!/usr/bin/env python3
"""Initialize stock groups - run once to setup database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.stock_manager import initialize_stock_groups, StockGroupManager
from data.db import Database

def main():
    print("Initializing stock groups...")

    # Initialize default groups
    initialize_stock_groups()

    # Show summary
    manager = StockGroupManager()
    summary = manager.get_group_summary()

    print("\n=== Stock Group Summary ===")
    for group, info in summary.items():
        print(f"\n{group}:")
        print(f"  Count: {info['count']}")
        print(f"  Sample: {', '.join(info['sample'])}")

    print("\n✅ Initialization complete!")
    print("\nNext steps:")
    print("  - large_cap group: Auto-updates every Monday from Finviz")
    print("  - etf group: Manually managed (add/remove via /add_etf, /remove_etf)")
    print("  - custom group: Manually managed (add/remove via /add, /remove)")

if __name__ == "__main__":
    main()
