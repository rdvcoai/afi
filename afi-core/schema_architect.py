import os
import json
import psycopg2
import google.generativeai as genai

# Configuración
DB_HOST = "afi_db"
DB_NAME = os.getenv("POSTGRES_DB", "afi_brain")
DB_USER = os.getenv("POSTGRES_USER", "afi_user")
# Ajuste: Buscar primero DB_PASS (definido en docker-compose) y luego POSTGRES_PASSWORD
DB_PASS = os.getenv("DB_PASS") or os.getenv("POSTGRES_PASSWORD")
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    print("❌ Error: GOOGLE_API_KEY no encontrada en variables de entorno.")
    exit(1)

genai.configure(api_key=API_KEY)

def get_db_connection():
    try:
        return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    except Exception as e:
        print(f"❌ Error conectando a Postgres: {e}")
        return None

def run_architect():
    print("🏗️ Iniciando el Arquitecto Financiero (Gemini)...")
    
    # 1. EL PROMPT DE DISEÑO (CON SABIDURÍA IMPLÍCITA)
    prompt = """
    ACTÚA COMO: Arquitecto de Base de Datos Senior experto en Finanzas Personales.
    
    OBJETIVO: Diseñar un esquema SQL (PostgreSQL) robusto para un sistema de "Family Office Personal".
    
    PRINCIPIOS DE DISEÑO (FILOSOFÍA INTERNA):
    1. No solo registres el "Qué" (Categoría), registra el "Por qué" (Necesidad vs. Deseo / Gasto Hormiga).
    2. Necesitamos separar claramente Flujo de Caja (Income/Expense) de Patrimonio (Assets/Liabilities).
    3. Soporte para múltiples monedas (aunque el default sea COP).
    4. Trazabilidad: Cada transacción debe saber de qué archivo fuente vino.
    
    TAREA:
    Genera el código SQL (DDL) para crear las tablas necesarias. Mínimo esperamos:
    - 'accounts' (Cuentas bancarias, efectivo, inversiones).
    - 'transactions' (El núcleo).
    - 'categories' (Pero con atributos de comportamiento, ej: is_fixed, is_discretionary).
    - 'audit_log' (Para saber qué archivo alimentó qué datos).
    
    SALIDA:
    Solo el bloque de código SQL puro. Nada de explicaciones, ni markdown (```sql).
    Usa 'IF NOT EXISTS' para seguridad.
    """

    # 2. CONSULTAR A GEMINI
    try:
        model = genai.GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(prompt)
        
        # Limpieza básica por si el modelo devuelve Markdown
        sql_script = response.text.replace("```sql", "").replace("```", "").strip()
        
        print("\n📜 Esquema Generado por IA:")
        print(sql_script[:500] + "...\n(truncado para visualización)\n")

        # 3. EJECUTAR EN POSTGRES
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute(sql_script)
            conn.commit()
            cur.close()
            conn.close()
            print("✅ Esquema SQL aplicado exitosamente en la Base de Datos.")
            print("   -> Ahora puedes ver las tablas en https://data.afi.rdv.net.co")
        else:
            print("❌ No se pudo establecer conexión para aplicar el esquema.")
            
    except Exception as e:
        print(f"❌ Error crítico en el Arquitecto: {e}")

if __name__ == "__main__":
    run_architect()
