import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import get_user_context, init_db, save_user_context


@pytest.fixture
def mock_db_conn():
    """Mock de conexión y cursor para evitar Postgres real."""
    with patch("database.get_conn") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Context managers para conn y cursor
        mock_get_conn.return_value = mock_conn
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        yield mock_cursor


def _executed_sql(mock_cursor):
    """Helper para extraer los SQL enviados al cursor."""
    return [args[0] for args, _ in mock_cursor.execute.call_args_list]


def test_init_db_creates_extension_and_tables(mock_db_conn):
    """Valida creación de extensión vectorial y tablas base."""
    init_db()
    calls = _executed_sql(mock_db_conn)
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in sql for sql in calls)
    assert any("CREATE TABLE IF NOT EXISTS user_state" in sql for sql in calls)
    assert any("CREATE TABLE IF NOT EXISTS financial_wisdom" in sql for sql in calls)


def test_save_user_context_upsert_full_payload(mock_db_conn):
    """Inserta/actualiza cuando se pasa file_context y mode."""
    save_user_context("573001234567", file_summary="Datos CSV...", mode="ONBOARDING")
    sql = mock_db_conn.execute.call_args[0][0]
    assert "INSERT INTO user_state" in sql
    assert "file_context" in sql and "current_mode" in sql
    assert "ON CONFLICT" in sql


def test_save_user_context_upsert_file_only(mock_db_conn):
    """Inserta/actualiza solo el file_context."""
    save_user_context("573001234567", file_summary="Datos CSV...")
    sql = mock_db_conn.execute.call_args[0][0]
    assert "INSERT INTO user_state" in sql
    assert "file_context" in sql
    assert "ON CONFLICT" in sql


def test_save_user_context_upsert_mode_only(mock_db_conn):
    """Inserta/actualiza solo el modo."""
    save_user_context("573001234567", mode="AUDIT")
    sql = mock_db_conn.execute.call_args[0][0]
    assert "INSERT INTO user_state" in sql
    assert "current_mode" in sql
    assert "ON CONFLICT" in sql


def test_get_user_context_found(mock_db_conn):
    """Recupera datos existentes."""
    mock_db_conn.fetchone.return_value = ("Datos CSV...", "ONBOARDING")
    result = get_user_context("573001234567")
    assert result == {"file_context": "Datos CSV...", "mode": "ONBOARDING"}


def test_get_user_context_empty(mock_db_conn):
    """Retorna None cuando no existe el usuario."""
    mock_db_conn.fetchone.return_value = None
    result = get_user_context("999999")
    assert result is None
