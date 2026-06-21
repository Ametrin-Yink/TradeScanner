"""Tests for AI audit logging."""
import pytest
from data.db import Database


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_ai_audit.db"
    return Database(db_path)


class TestAIAuditLog:
    """Test AI audit log table and methods."""

    def test_create_ai_audit_table(self, test_db):
        """Should create ai_audit_log table."""
        test_db.create_ai_audit_table()
        with test_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_audit_log'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 'ai_audit_log'

    def test_log_ai_call(self, test_db):
        """Should insert an AI call record."""
        test_db.create_ai_audit_table()
        test_db.log_ai_call(
            call_type='sector_analysis',
            sector_name='Technology',
            prompt_hash='abc123',
            response_hash='def456',
            model='deepseek-v4-pro',
            temperature=0.0,
            seed=42,
            tokens_in=500,
            tokens_out=200,
            cost=0.00036
        )
        with test_db.get_connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            cursor = conn.execute("SELECT * FROM ai_audit_log")
            rows = [dict(row) for row in cursor.fetchall()]
        assert len(rows) == 1
        row = rows[0]
        assert row['call_type'] == 'sector_analysis'
        assert row['sector_name'] == 'Technology'
        assert row['prompt_hash'] == 'abc123'
        assert row['response_hash'] == 'def456'
        assert row['model'] == 'deepseek-v4-pro'
        assert row['temperature'] == 0.0
        assert row['seed'] == 42
        assert row['tokens_in'] == 500
        assert row['tokens_out'] == 200
        assert row['cost_estimate'] == 0.00036
        assert row['created_at'] is not None

    def test_log_multiple_calls(self, test_db):
        """Should insert multiple AI call records."""
        test_db.create_ai_audit_table()
        test_db.log_ai_call(
            call_type='sector_analysis', sector_name='Technology',
            prompt_hash='abc', response_hash='def',
            model='deepseek-v4-pro', temperature=0.0, seed=42,
            tokens_in=500, tokens_out=200, cost=0.00036
        )
        test_db.log_ai_call(
            call_type='regime_analysis', sector_name='',
            prompt_hash='ghi', response_hash='jkl',
            model='deepseek-v4-pro', temperature=0.1, seed=99,
            tokens_in=1000, tokens_out=500, cost=0.00083
        )
        with test_db.get_connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            cursor = conn.execute("SELECT * FROM ai_audit_log ORDER BY id")
            rows = [dict(row) for row in cursor.fetchall()]
        assert len(rows) == 2
        assert rows[0]['call_type'] == 'sector_analysis'
        assert rows[1]['call_type'] == 'regime_analysis'
