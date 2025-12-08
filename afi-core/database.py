import os
import psycopg2

# Configuración
DB_HOST = os.getenv("DB_HOST", "afi_db")
DB_USER = os.getenv("DB_USER", "afi_user")
DB_PASS = os.getenv("DB_PASS", "password")
DB_NAME = os.getenv("DB_NAME", "afi_brain")


def get_conn():
    conn = psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME)
    conn.autocommit = True
    return conn


def init_db():
    """Crea las tablas necesarias si no existen."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_state (
                    phone TEXT PRIMARY KEY,
                    current_mode TEXT DEFAULT 'NORMAL',
                    file_context TEXT,
                    chat_history JSONB DEFAULT '[]'::jsonb,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")


def save_user_context(phone, file_summary=None, mode=None):
    """Guarda/actualiza el estado del usuario."""
    if not phone:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            updates = []
            params = []
            if file_summary is not None:
                updates.append("file_context = %s")
                params.append(file_summary)
            if mode is not None:
                updates.append("current_mode = %s")
                params.append(mode)
            if updates:
                params.append(phone)
                query = f"UPDATE user_state SET {', '.join(updates)} WHERE phone = %s"
                cur.execute(query, tuple(params))
                if cur.rowcount == 0:
                    cur.execute(
                        "INSERT INTO user_state (phone, file_context, current_mode) VALUES (%s, %s, %s)",
                        (phone, file_summary or "", mode or "NORMAL"),
                    )


def get_user_context(phone):
    """Recupera memoria del usuario."""
    if not phone:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_context, current_mode FROM user_state WHERE phone = %s", (phone,))
            row = cur.fetchone()
            if row:
                return {"file_context": row[0], "mode": row[1]}
            return None
