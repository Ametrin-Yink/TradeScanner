# core/tag_manager.py
"""Tag-based stock universe management (replaces SectorManager)."""
import logging
from typing import Optional, List, Dict

from data.db import Database

logger = logging.getLogger(__name__)


class TagManager:
    def __init__(self):
        self.db = None  # set per-call to allow fresh DB instances

    # -- Tags --

    def get_tags(self, db: Database) -> List[Dict]:
        """Return all tags with stock counts."""
        conn = db.get_connection()
        rows = conn.execute("""
            SELECT t.id, t.name, t.type, t.etf,
                   COUNT(st.symbol) as stock_count
            FROM tags t
            LEFT JOIN stock_tags st ON t.id = st.tag_id
            GROUP BY t.id
            ORDER BY t.name
        """).fetchall()
        return [
            {'name': r[1], 'type': r[2], 'etf': r[3] or '', 'stock_count': r[4]}
            for r in rows
        ]

    def add_tag(self, name: str, etf: str, db: Database, tag_type: str = 'sector'):
        conn = db.get_connection()
        conn.execute(
            "INSERT OR IGNORE INTO tags (name, type, etf) VALUES (?, ?, ?)",
            (name.strip(), tag_type, etf.strip().upper())
        )
        conn.commit()

    def remove_tag(self, name: str, db: Database):
        conn = db.get_connection()
        tag = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if not tag:
            raise ValueError(f"Tag '{name}' not found")
        conn.execute("DELETE FROM stock_tags WHERE tag_id = ?", (tag[0],))
        conn.execute("DELETE FROM tags WHERE id = ?", (tag[0],))
        conn.commit()

    # -- Tag stocks --

    def get_tag_stocks(self, tag_name: str, db: Database) -> List[Dict]:
        conn = db.get_connection()
        rows = conn.execute("""
            SELECT s.symbol, s.name, COALESCE(s.market_cap, 0),
                   COALESCE(t1.ret_5d, 0) as ret_5d,
                   COALESCE(t1.volume_ratio, 1.0) as vol_ratio
            FROM stocks s
            JOIN stock_tags st ON s.symbol = st.symbol
            JOIN tags t ON st.tag_id = t.id
            LEFT JOIN tier1_cache t1 ON s.symbol = t1.symbol
            WHERE t.name = ? AND s.is_active = 1
            ORDER BY s.symbol
        """, (tag_name,)).fetchall()
        symbols = [r[0] for r in rows]
        daily_changes = self._get_daily_changes(symbols, db)
        return [
            {'symbol': r[0], 'name': r[1], 'market_cap': r[2],
             'ret_5d': r[3], 'vol_ratio': r[4],
             'daily_change': daily_changes.get(r[0])}
            for r in rows
        ]

    def _get_daily_changes(self, symbols: List[str], db: Database) -> Dict[str, Optional[float]]:
        """Compute true 1-day price change for a list of symbols from market_data.
        Returns dict mapping symbol -> daily_change_pct or None."""
        if not symbols:
            return {}
        conn = db.get_connection()
        # Check if market_data table exists (may not in test databases)
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_data'"
        ).fetchone()
        if not exists:
            return {s: None for s in symbols}
        placeholders = ','.join(['?' for _ in symbols])
        rows = conn.execute(f"""
            SELECT symbol, close, date FROM market_data
            WHERE symbol IN ({placeholders})
            ORDER BY symbol, date DESC
        """, symbols).fetchall()
        # Group by symbol, take first two entries for each
        by_symbol = {}
        for symbol, close, date in rows:
            if symbol not in by_symbol:
                by_symbol[symbol] = []
            if len(by_symbol[symbol]) < 2:
                by_symbol[symbol].append(close)
        result = {}
        for sym in symbols:
            closes = by_symbol.get(sym, [])
            if len(closes) == 2 and closes[1] > 0:
                result[sym] = (closes[0] - closes[1]) / closes[1] * 100
            else:
                result[sym] = None
        return result

    def add_stock_to_tag(self, symbol: str, tag_name: str, db: Database):
        conn = db.get_connection()
        tag = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
        if not tag:
            raise ValueError(f"Tag '{tag_name}' not found")
        conn.execute(
            "INSERT OR IGNORE INTO stock_tags (symbol, tag_id) VALUES (?, ?)",
            (symbol.upper(), tag[0])
        )
        conn.commit()

    def remove_stock_from_tag(self, symbol: str, tag_name: str, db: Database):
        conn = db.get_connection()
        tag = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
        if not tag:
            raise ValueError(f"Tag '{tag_name}' not found")
        conn.execute(
            "DELETE FROM stock_tags WHERE symbol = ? AND tag_id = ?",
            (symbol.upper(), tag[0])
        )
        conn.commit()

    # -- Pipeline --

    def get_pipeline_stocks(self, tag_name: Optional[str], db: Database) -> List[str]:
        """Return symbols for a tag (or all unique if tag_name is None)."""
        conn = db.get_connection()
        if tag_name:
            rows = conn.execute("""
                SELECT DISTINCT st.symbol FROM stock_tags st
                JOIN tags t ON st.tag_id = t.id
                WHERE t.name = ?
            """, (tag_name,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM stock_tags"
            ).fetchall()
        return [r[0] for r in rows]

    def get_tag_daily_change(self, tag_name: str, db: Database) -> Optional[float]:
        """Compute aggregate daily change for a tag from constituent stocks."""
        stocks = self.get_tag_stocks(tag_name, db)
        changes = [s['daily_change'] for s in stocks if s.get('daily_change') is not None]
        if not changes:
            return None
        return sum(changes) / len(changes)

    # -- Search --

    def search_stocks(self, q: str, db: Database, limit: int = 20) -> List[Dict]:
        """Search stocks by symbol or name. Deduplicated by symbol."""
        conn = db.get_connection()
        rows = conn.execute("""
            SELECT DISTINCT s.symbol, s.name, s.market_cap,
                   GROUP_CONCAT(DISTINCT t.name) as tags
            FROM stocks s
            LEFT JOIN stock_tags st ON s.symbol = st.symbol
            LEFT JOIN tags t ON st.tag_id = t.id
            WHERE s.is_active = 1
              AND (s.symbol LIKE ? OR s.name LIKE ?)
            GROUP BY s.symbol
            LIMIT ?
        """, (f'%{q}%', f'%{q}%', limit)).fetchall()
        return [
            {'symbol': r[0], 'name': r[1], 'market_cap': r[2], 'tags': r[3] or ''}
            for r in rows
        ]

    def get_unassigned_stocks(self, db: Database, limit: int = 100) -> List[Dict]:
        """Return active stocks with no tag assignments."""
        conn = db.get_connection()
        rows = conn.execute("""
            SELECT s.symbol, s.name, s.market_cap
            FROM stocks s
            WHERE s.is_active = 1
              AND s.symbol NOT IN (SELECT DISTINCT symbol FROM stock_tags)
            LIMIT ?
        """, (limit,)).fetchall()
        return [
            {'symbol': r[0], 'name': r[1], 'market_cap': r[2]}
            for r in rows
        ]

    def seed_from_csv(self, db: Database) -> Dict:
        """Seed tag assignments from CSV (kept for backward compat)."""
        import csv
        from pathlib import Path
        from core.constants import SECTOR_ETFS

        csv_path = Path(__file__).parent.parent / "nasdaq_stocklist_screener.csv"
        if not csv_path.exists():
            logger.warning("Seed CSV not found: %s", csv_path)
            return {'added': 0, 'tags': 0}

        added = 0
        tag_names = set()
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get('Symbol', '').strip().upper()
                sector = row.get('Sector', '').strip()
                if not symbol or not sector:
                    continue
                etf = SECTOR_ETFS.get(sector, '')
                self.add_tag(sector, etf, db)
                try:
                    self.add_stock_to_tag(symbol, sector, db)
                    added += 1
                    tag_names.add(sector)
                except Exception:
                    pass

        return {'added': added, 'tags': len(tag_names)}
