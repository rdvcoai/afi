import json
import os
import time

import PyPDF2
import google.generativeai as genai

from database import get_conn

# Configuración
BOOKS_DIR = "/app/data/books"


def extract_text_from_pdfs():
    """Lee todos los PDFs del directorio."""
    texts = []
    if not os.path.exists(BOOKS_DIR):
        print(f"⚠️ Directorio {BOOKS_DIR} no existe.")
        return []

    for filename in os.listdir(BOOKS_DIR):
        if filename.endswith(".pdf"):
            path = os.path.join(BOOKS_DIR, filename)
            try:
                reader = PyPDF2.PdfReader(path)
                text = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        # Limpieza de caracteres nulos que rompen Postgres
                        page_text = page_text.replace("\x00", "")
                        text += page_text + "\n"

                texts.append({"title": filename, "content": text})
            except Exception as e:
                print(f"❌ Error leyendo {filename}: {e}")
    return texts


def chunk_text(text, chunk_size=1000):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def get_embedding(text):
    model = "models/text-embedding-004"
    text = text.replace("\n", " ")
    try:
        return genai.embed_content(model=model, content=text, task_type="retrieval_document")["embedding"]
    except Exception as e:
        print(f"⚠️ Error API Gemini: {e}. Reintentando en 5s...")
        time.sleep(5)
        return genai.embed_content(model=model, content=text, task_type="retrieval_document")["embedding"]


def book_exists(cursor, title):
    """Verifica si el libro ya tiene al menos un vector guardado."""
    cursor.execute("SELECT 1 FROM financial_wisdom WHERE metadata->>'source' = %s LIMIT 1", (title,))
    return cursor.fetchone() is not None


def ingest_wisdom():
    print("🧠 Iniciando Ingesta de Sabiduría (Versión Corregida)...")

    books = extract_text_from_pdfs()
    conn = get_conn()
    cursor = conn.cursor()

    total_new_chunks = 0

    for book in books:
        # Check de idempotencia
        if book_exists(cursor, book["title"]):
            print(f"⏩ Saltando '{book['title']}' (Ya existe en DB).")
            continue

        chunks = chunk_text(book["content"])
        print(f"📚 Procesando '{book['title']}' ({len(chunks)} fragmentos)...")

        for i, chunk in enumerate(chunks):
            try:
                vector = get_embedding(chunk)

                # FIX: Usar json.dumps para comillas dobles válidas
                metadata_json = json.dumps({"source": book["title"]})

                cursor.execute(
                    """
                    INSERT INTO financial_wisdom (content, metadata, embedding)
                    VALUES (%s, %s, %s)
                    """,
                    (chunk, metadata_json, vector),
                )

                total_new_chunks += 1

                # Commit parcial cada 50 chunks para no perder progreso
                if total_new_chunks % 50 == 0:
                    conn.commit()
                    print(f"   🔹 {total_new_chunks} fragmentos guardados...")

            except Exception as e:
                print(f"❌ Error en fragmento {i} de '{book['title']}': {e}")

        conn.commit()  # Commit final del libro
        print(f"✅ Libro '{book['title']}' completado.")

    conn.close()
    print(f"🏁 Ingesta finalizada. Total fragmentos nuevos: {total_new_chunks}")


if __name__ == "__main__":
    ingest_wisdom()
