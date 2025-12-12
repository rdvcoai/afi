import datetime
import os
from typing import Iterable, List, Optional, Sequence, Tuple, Any

from psycopg2.extras import execute_values

from database import get_conn

DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "COP")
DEFAULT_ACCOUNT_TYPE = os.getenv("DEFAULT_ACCOUNT_TYPE", "Wallet")


def execute_insert(sql: str, params: Optional[Tuple] = None, user_id: Optional[int] = None) -> None:
    """Ejecuta una sentencia SQL de inserción/actualización."""
    with get_conn(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def execute_query(sql: str, params: Optional[Tuple] = None, fetch_one: bool = False, user_id: Optional[int] = None) -> Any:
    """Ejecuta una sentencia SQL de consulta."""
    with get_conn(user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if fetch_one:
                return cur.fetchone()
            return cur.fetchall()


def get_schema_info() -> dict:
    """Devuelve un mapa tabla->columnas para alimentar al agente SQL."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
                """
            )
            schema: dict = {}
            for table_name, column_name, data_type in cur.fetchall():
                schema.setdefault(table_name, []).append({"name": column_name, "type": data_type})
            return schema


def _ensure_base_schema(cur) -> None:
    """Guarantee core tables exist before writing data."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS currencies (
            currency_code CHAR(3) PRIMARY KEY,
            currency_name VARCHAR(50),
            symbol VARCHAR(5)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS master_categories (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL,
            type VARCHAR(20) NOT NULL CHECK (type IN ('fixed', 'variable', 'savings'))
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_budgets (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            category_id INTEGER REFERENCES master_categories(id),
            month DATE NOT NULL,
            amount_limit DECIMAL(15,2) NOT NULL DEFAULT 0,
            UNIQUE(user_id, category_id, month)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS account_types (
            type_id SERIAL PRIMARY KEY,
            type_name VARCHAR(50) NOT NULL UNIQUE,
            classification VARCHAR(20) NOT NULL DEFAULT 'ASSET'
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            account_id SERIAL PRIMARY KEY,
            account_name VARCHAR(100) NOT NULL UNIQUE,
            account_type_id INT REFERENCES account_types(type_id),
            currency_code CHAR(3) REFERENCES currencies(currency_code) DEFAULT %s,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        (DEFAULT_CURRENCY,),
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id SERIAL PRIMARY KEY,
            account_id INT REFERENCES accounts(account_id) ON DELETE CASCADE,
            date DATE NOT NULL,
            amount NUMERIC(19, 4) NOT NULL,
            description TEXT,
            category VARCHAR(100),
            status VARCHAR(20) DEFAULT 'CLEARED',
            import_source VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        ALTER TABLE IF EXISTS transactions
        ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES master_categories(id);
        """
    )
    cur.execute(
        """
        INSERT INTO currencies (currency_code, currency_name, symbol)
        VALUES (%s, %s, %s)
        ON CONFLICT (currency_code) DO NOTHING;
        """,
        (DEFAULT_CURRENCY, "Local Currency", "$"),
    )
    cur.execute(
        """
        INSERT INTO account_types (type_name, classification)
        VALUES (%s, 'ASSET')
        ON CONFLICT (type_name) DO NOTHING;
        """,
        (DEFAULT_ACCOUNT_TYPE,),
    )

    # Columnas adicionales para multi-tenant y HITL
    cur.execute("ALTER TABLE IF EXISTS accounts ADD COLUMN IF NOT EXISTS user_id INTEGER DEFAULT 1;")
    cur.execute(
        """
        ALTER TABLE IF EXISTS transactions
        ADD COLUMN IF NOT EXISTS confidence_score FLOAT DEFAULT 1.0,
        ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS review_needed BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS user_id INTEGER DEFAULT 1;
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_monthly_budgets_user_month ON monthly_budgets(user_id, month);")


def _coerce_date(value: object) -> datetime.date:
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return datetime.date.today()


def ensure_account(account_name: str, account_type: str = DEFAULT_ACCOUNT_TYPE, currency: str = DEFAULT_CURRENCY) -> Optional[int]:
    if not account_name:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_base_schema(cur)
            cur.execute(
                """
                INSERT INTO account_types (type_name, classification)
                VALUES (%s, 'ASSET')
                ON CONFLICT (type_name) DO NOTHING;
                """,
                (account_type,),
            )
            cur.execute(
                """
                INSERT INTO accounts (account_name, account_type_id, currency_code)
                VALUES (%s, (SELECT type_id FROM account_types WHERE type_name = %s LIMIT 1), %s)
                ON CONFLICT (account_name) DO NOTHING;
                """,
                (account_name, account_type, currency),
            )
            cur.execute("SELECT account_id FROM accounts WHERE account_name = %s LIMIT 1;", (account_name,))
            row = cur.fetchone()
            return row[0] if row else None


def list_accounts() -> List[Tuple[int, str]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_base_schema(cur)
            cur.execute("SELECT account_id, account_name FROM accounts ORDER BY account_name;")
            return cur.fetchall()


def insert_transactions(account_id: int, txs: Sequence[dict], import_source: Optional[str] = None, status: str = "CLEARED") -> int:
    if not account_id or not txs:
        return 0
    rows: List[Tuple] = []
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        amount_raw = tx.get("amount")
        try:
            amount_val = float(amount_raw)
        except Exception:
            continue
        if amount_val == 0:
            continue
        description = tx.get("description") or tx.get("payee_name") or tx.get("payee") or "Movimiento"
        category = tx.get("category")
        import_src = tx.get("import_source") or import_source
        date_val = _coerce_date(tx.get("date") or datetime.date.today())
        rows.append((account_id, date_val, amount_val, description, category, status, import_src))

    if not rows:
        return 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_base_schema(cur)
            execute_values(
                cur,
                """
                INSERT INTO transactions (account_id, date, amount, description, category, status, import_source)
                VALUES %s
                """,
                rows,
            )
    return len(rows)


def record_transaction(
    account_name: str,
    amount: float,
    date_value: object,
    description: str,
    category: Optional[str] = None,
    import_source: Optional[str] = None,
    status: str = "CLEARED",
    account_type: str = DEFAULT_ACCOUNT_TYPE,
) -> Optional[int]:
    account_id = ensure_account(account_name, account_type=account_type)
    if not account_id:
        return None
    tx = {
        "amount": amount,
        "date": _coerce_date(date_value),
        "description": description,
        "category": category,
        "import_source": import_source,
    }
    inserted = insert_transactions(account_id, [tx], status=status)
    return inserted


def bulk_categorize(category_name: str, keywords: Iterable[str]) -> int:
    if not category_name:
        return 0
    keywords_list = [k for k in keywords if k]
    if not keywords_list:
        return 0
    total_updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_base_schema(cur)
            for kw in keywords_list:
                cur.execute(
                    """
                    UPDATE transactions
                    SET category = %s
                    WHERE LOWER(description) LIKE LOWER(%s);
                    """,
                    (category_name, f"%{kw}%"),
                )
                total_updated += cur.rowcount
    return total_updated


def delete_all_accounts_and_transactions() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_base_schema(cur)
            cur.execute("DELETE FROM transactions;")
            cur.execute("DELETE FROM accounts;")
