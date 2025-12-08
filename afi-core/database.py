import os
import time
import psycopg2
from psycopg2.extras import Json

# Configuración
DB_HOST = os.getenv("DB_HOST", "afi_db")
DB_USER = os.getenv("DB_USER", "afi_user")
DB_PASS = os.getenv("DB_PASS", "password")
DB_NAME = os.getenv("DB_NAME", "afi_brain")


def get_conn():
    conn = psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME)
    conn.autocommit = True
    return conn


def wait_for_db(retries: int = 5, delay: int = 2):
    """Espera activa hasta que la DB esté lista para conexiones."""
    attempts = retries
    while attempts > 0:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
            print("✅ Conexión a Postgres exitosa.")
            return
        except psycopg2.OperationalError:
            print("⏳ Esperando a Postgres...")
            time.sleep(delay)
            attempts -= 1
    print("❌ No se pudo conectar a Postgres.")


def init_db():
    """Inicializa esquemas y extensiones."""
    wait_for_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_wisdom (
                    id BIGSERIAL PRIMARY KEY,
                    content TEXT,
                    metadata JSONB,
                    embedding VECTOR(768)
                );
                """
            )

            # NUEVA TABLA: USUARIOS (PERFIL PERSONAL)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    phone TEXT PRIMARY KEY,
                    name TEXT,
                    role TEXT DEFAULT 'user', -- 'admin' para Diego
                    profile_status TEXT DEFAULT 'incomplete', -- 'incomplete', 'active'
                    financial_goals TEXT, -- Resumen de metas (ej: 'Pagar deuda Nubank')
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # SEED: CREAR ADMIN (DIEGO) AUTOMÁTICAMENTE
            # Asegura que tu número siempre tenga rol admin
            admin_phone = os.getenv("ADMIN_PHONE", "57300.......") # Definir en .env
            cur.execute("""
                INSERT INTO users (phone, name, role)
                VALUES (%s, 'Diego', 'admin')
                ON CONFLICT (phone) DO NOTHING;
            """, (admin_phone,))

            print("✅ Esquema de Usuarios sincronizado.")


def save_user_context(phone, file_summary=None, mode=None):
    """Guarda/actualiza el estado del usuario."""
    if not phone:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_state (phone, file_context, current_mode)
                VALUES (%s, %s, %s)
                ON CONFLICT (phone) DO UPDATE SET
                    file_context = COALESCE(EXCLUDED.file_context, user_state.file_context),
                    current_mode = COALESCE(EXCLUDED.current_mode, user_state.current_mode),
                    last_updated = CURRENT_TIMESTAMP;
                """,
                (phone, file_summary, mode),
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
