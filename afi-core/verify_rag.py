import os
import psycopg2
import google.generativeai as genai

# Configuración
DB_HOST = os.getenv("DB_HOST", "afi_db")
DB_NAME = os.getenv("DB_NAME", "afi_brain")
DB_USER = os.getenv("DB_USER", "afi_user")
DB_PASS = os.getenv("DB_PASS")
API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=API_KEY)

def get_conn():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)

def test_query(question):
    print(f"❓ Pregunta: '{question}'")
    
    # 1. Embed
    resp = genai.embed_content(model="models/text-embedding-004", content=question, task_type="retrieval_query")
    embedding = resp["embedding"]
    vec_literal = "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"

    # 2. Search
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT content, source FROM financial_wisdom ORDER BY embedding <-> %s::vector LIMIT 2",
        (vec_literal,)
    )
    rows = cur.fetchall()
    
    print(f"📚 Resultados encontrados: {len(rows)}\n")
    for i, (content, source) in enumerate(rows):
        print(f"--- Resultado {i+1} (Fuente: {source}) ---")
        print(content[:300] + "...") # Preview
        print("-------------------------------------------\n")

if __name__ == "__main__":
    test_query("What is the 4% rule?")
