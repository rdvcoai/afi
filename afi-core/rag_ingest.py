import os
import time
import google.generativeai as genai
import psycopg2
from psycopg2.extras import execute_values
import PyPDF2

# Configuración
LIBRARY_PATH = "/app/data/books"
DB_HOST = os.getenv("DB_HOST", "afi_db")
DB_NAME = os.getenv("DB_NAME", "afi_brain")
DB_USER = os.getenv("DB_USER", "afi_user")
DB_PASS = os.getenv("DB_PASS")
API_KEY = os.getenv("GOOGLE_API_KEY")

EMBEDDING_MODEL = "models/text-embedding-004"

genai.configure(api_key=API_KEY)

def get_conn():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

def get_processed_files(cur):
    """Consulta qué archivos ya existen en la DB para no repetirlos"""
    try:
        cur.execute("SELECT DISTINCT source FROM financial_wisdom;")
        return {row[0] for row in cur.fetchall()}
    except psycopg2.errors.UndefinedTable:
        return set()

def clear_file_data(cur, filename):
    """Borra datos de un archivo específico para re-procesarlo limpio"""
    cur.execute("DELETE FROM financial_wisdom WHERE source = %s;", (filename,))

def embed_with_retry(text, retries=5):
    delay = 1
    for i in range(retries):
        try:
            result = genai.embed_content(
                model=EMBEDDING_MODEL,
                content=text,
                task_type="retrieval_document"
            )
            return result['embedding']
        except Exception as e:
            if "429" in str(e) or "Resource has been exhausted" in str(e):
                print(f"   ⏳ API Saturada. Esperando {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"   ❌ Error en embedding: {e}")
                return None
    return None

def ingest_library():
    print("🚀 Iniciando Ingesta Inteligente (Con Resume)...")
    
    conn = get_conn()
    cur = conn.cursor()

    # Asegurar tabla
    cur.execute("""
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS financial_wisdom (
            id SERIAL PRIMARY KEY,
            content TEXT,
            source VARCHAR(255),
            embedding vector(768)
        );
    """)
    conn.commit()

    # 1. RECUPERAR ESTADO ACTUAL
    processed_files = get_processed_files(cur)
    print(f"📊 Estado Actual: {len(processed_files)} libros ya en base de datos.")

    if not os.path.exists(LIBRARY_PATH):
        print(f"⚠️ La ruta {LIBRARY_PATH} no existe.")
        return

    pdf_files = [f for f in os.listdir(LIBRARY_PATH) if f.endswith(".pdf")]
    
    if not pdf_files:
        print("⚠️ Carpeta vacía.")
        return

    for filename in pdf_files:
        # 2. CHECK DE RESUME
        if filename in processed_files:
            print(f"⏭️  Saltando '{filename}' (Ya procesado).")
            continue
        
        # Si llegamos aquí, el archivo es nuevo O se quedó a medias.
        # Por seguridad, borramos cualquier rastro previo de este archivo específico
        # para evitar duplicados si falló al 50%.
        clear_file_data(cur, filename)
        conn.commit()

        print(f"\n📖 Procesando Nuevo Libro: {filename}")
        file_path = os.path.join(LIBRARY_PATH, filename)
        
        try:
            full_text = ""
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text()
                    if text: full_text += text + "\n"
        except Exception as e:
            print(f"   ❌ Error leyendo PDF: {e}")
            continue

        if not full_text: continue

        # Chunking
        chunk_size = 1000
        overlap = 100
        chunks = [full_text[i:i + chunk_size].strip() for i in range(0, len(full_text), chunk_size - overlap) if len(full_text[i:i+chunk_size].strip()) > 50]

        print(f"   🧩 {len(chunks)} fragmentos detectados.")

        batch_data = []
        batch_size = 50 
        
        for i, chunk in enumerate(chunks):
            # Sanitize chunk to remove null characters (0x00)
            chunk = chunk.replace('\x00', '')
            vector = embed_with_retry(chunk)
            if vector:
                batch_data.append((chunk, filename, vector))
            
            if len(batch_data) >= batch_size or i == len(chunks) - 1:
                if batch_data:
                    execute_values(cur, 
                        "INSERT INTO financial_wisdom (content, source, embedding) VALUES %s", 
                        batch_data
                    )
                    conn.commit() # COMMIT PARCIAL: Guarda el progreso
                    print(f"   💾 Guardando... {int((i+1)/len(chunks)*100)}%", end="\r")
                    batch_data = []
        
        print(f"\n   ✅ Libro '{filename}' completado y asegurado.")

    cur.close()
    conn.close()
    print("\n🏁 Biblioteca Sincronizada.")

if __name__ == "__main__":
    ingest_library()