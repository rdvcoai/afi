import os
import time
import psycopg2
from psycopg2.extras import Json

# Configuración
DB_HOST = os.getenv("DB_HOST", "afi_db")
DB_USER = os.getenv("DB_USER", "afi_user")
DB_PASS = os.getenv("DB_PASS", "password")
DB_NAME = os.getenv("DB_NAME", "afi_brain")


def get_conn(user_id=None):
    conn = psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME)
    conn.autocommit = True
    if user_id is not None:
        with conn.cursor() as cur:
            cur.execute("SET app.current_user_id = %s;", (str(user_id),))
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
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_financial_wisdom_embedding
                ON financial_wisdom USING ivfflat (embedding vector_cosine_ops);
                """
            )

            # NUEVA TABLA: USUARIOS (PERFIL PERSONAL)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    phone TEXT UNIQUE NOT NULL,
                    name TEXT,
                    role TEXT DEFAULT 'user', -- 'admin' para Diego
                    profile_status TEXT DEFAULT 'incomplete', -- 'incomplete', 'active'
                    financial_goals TEXT, -- Resumen de metas (ej: 'Pagar deuda Nubank')
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Migrar esquema legado (phone como PK) a modelo con id entero
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS id SERIAL;")
            cur.execute("ALTER TABLE users ALTER COLUMN phone SET NOT NULL;")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique ON users(phone);")
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                            ON tc.constraint_name = kcu.constraint_name
                        WHERE tc.table_name = 'users'
                          AND tc.constraint_type = 'PRIMARY KEY'
                          AND kcu.column_name = 'id'
                    ) THEN
                        ALTER TABLE users DROP CONSTRAINT IF EXISTS users_pkey;
                        ALTER TABLE users ADD CONSTRAINT users_pkey PRIMARY KEY (id);
                    END IF;
                END $$;
                """
            )

            # SEED ADMIN (sin nombre, forzando onboarding limpio)
            admin_phone = os.getenv("ADMIN_PHONE")  # Definir en .env
            if admin_phone:
                cur.execute("""
                    INSERT INTO users (phone, role, profile_status)
                    VALUES (%s, 'admin', 'incomplete')
                    ON CONFLICT (phone) DO UPDATE
                        SET profile_status = 'incomplete', name = NULL;
                """, (admin_phone,))

            # Campo de datos pendientes para ingestas (limbo)
            cur.execute("""
                ALTER TABLE user_state
                ADD COLUMN IF NOT EXISTS pending_file_data JSONB;
            """)

            # Sesiones y OTPs para autenticación persistente
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    phone TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS otps (
                    phone TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL
                );
                """
            )

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


# Helpers para datos pendientes de importación
def save_pending_data(phone, data):
    if not phone:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_state SET pending_file_data = %s WHERE phone = %s", (Json(data), phone))


def get_pending_data(phone):
    if not phone:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pending_file_data FROM user_state WHERE phone = %s", (phone,))
            row = cur.fetchone()
            return row[0] if row else None


def clear_pending_data(phone):
    if not phone:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE user_state SET pending_file_data = NULL WHERE phone = %s", (phone,))
