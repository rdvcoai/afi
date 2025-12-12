import json
import os
from typing import List, Optional

import google.generativeai as genai
import pandas as pd

from db_ops import get_conn, get_schema_info, execute_query

# Configuración
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
# Compatibilidad: fijamos familia 2.5; se puede sobreescribir con GENAI_MODEL.
MODEL_NAME = os.getenv("GENAI_MODEL", "gemini-2.5-pro")
EMBEDDING_MODEL = "models/text-embedding-004"

def get_wisdom_context(query: str) -> str:
    """Recupera fragmentos relevantes de los libros ingestados."""
    try:
        # Generar embedding de la pregunta
        resp = genai.embed_content(model=EMBEDDING_MODEL, content=query, task_type="retrieval_query")
        vec = resp['embedding']
        vec_literal = "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"
        
        conn = get_conn()
        cur = conn.cursor()
        # Búsqueda Vectorial (Los 2 fragmentos más cercanos)
        # Nota: Usamos la columna 'source' que arreglamos en el paso anterior
        cur.execute("SELECT content, source FROM financial_wisdom ORDER BY embedding <-> %s::vector LIMIT 2", (vec_literal,))
        rows = cur.fetchall()
        conn.close()
        
        if rows:
            snippets = []
            for content, source in rows:
                source_name = source or "Sabiduría General"
                snippets.append(f"[{source_name}] {content}")
            return "\n\n".join(snippets)
        return ""
    except Exception as e:
        print(f"⚠️ RAG Warning: {e}")
        return ""


def _format_history(history: List[dict]) -> str:
    if not history:
        return ""
    recent = history[-2:]
    formatted = []
    for h in recent:
        role = h.get("role") or "user"
        content = h.get("content") or ""
        formatted.append(f"{role.upper()}: {content}")
    return "\n".join(formatted)


def process_query(user_query: str, user_id: Optional[str] = None, history: Optional[List[dict]] = None) -> dict:
    """
    Traduce lenguaje natural a SQL + instrucción de visualización usando Gemini.
    Incluye contexto breve de conversación (últimos 2 mensajes) y Sabiduría Financiera (RAG).
    """
    print(f"🧠 Analizando pregunta: {user_query}")

    # 1. Recuperar Sabiduría (RAG)
    wisdom = get_wisdom_context(user_query)
    
    schema = get_schema_info()
    context_str = _format_history(history or [])

    # 2. Verificar datos de presupuesto y ajustar el prompt
    budget_context = ""
    try:
        # Check if monthly_budgets table has any entries
        budget_entries = execute_query("SELECT COUNT(*) FROM monthly_budgets", fetch_one=True)
        if budget_entries and budget_entries[0] > 0:
            # Check if the user's query is budget-related
            if any(kw in user_query.lower() for kw in ["presupuesto", "budget", "meta", "gasto", "limite"]):
                budget_context = """
                **CONTEXTO ADICIONAL: PRESPUESTOS MENSUALES**
                Tienes acceso a la tabla 'monthly_budgets' que define las metas de gasto por categoría y usuario.
                Si el usuario pregunta por 'presupuesto', 'metas' o 'límites de gasto', compara `sum(transactions.amount)` (gastos, que son negativos) agrupados por `category_id` con `monthly_budgets.amount_limit`.
                Considera la fecha `monthly_budgets.month` para filtrar por el mes actual.
                """
    except Exception as e:
        print(f"⚠️ Error al verificar presupuestos: {e}")


    prompt = f"""
    ACTÚA COMO: CFO Personal Experto (AFI) y Data Analyst.
    
    SABIDURÍA INTERNA (Tus Principios Financieros):
    {wisdom}
    
    {budget_context}

    INSTRUCCIÓN DE PERSONALIDAD:
    - Usa la sabiduría anterior para aconsejar, pero INTERNALÍZALA.
    - NO digas "El libro dice...". Di "Te sugiero..." o "La clave es...".
    - Si la pregunta es técnica ("cuánto gasté"), responde directo con datos.
    - Si es estratégica ("qué hago con mi dinero"), combina datos y sabiduría.

    CONTEXTO PREVIO:
    {context_str}

    ESQUEMA DB (Postgres):
    {schema}

    PREGUNTA ACTUAL: "{user_query}"

    OBJETIVO TÉCNICO:
    1. Generar SQL seguro (Postgres) para responder si hace falta.
    2. Decidir visualización.
    3. Si la pregunta es ambigua, responde con viz_type "text" y pide aclaración.

    SALIDA JSON ESTRICTA:
    {{
        "sql": "SELECT ...",  // o null si solo texto
        "viz_type": "bar_chart" | "line_chart" | "metric" | "table" | "text",
        "title": "Título corto",
        "explanation": "Texto explicativo (aquí va tu consejo con personalidad)"
    }}
    """

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
        json_text = (response.text or "").replace("```json", "").replace("```", "").strip()
        result = json.loads(json_text)

        sql_query = result.get("sql")
        viz_type = result.get("viz_type", "table")

        # Si es solo texto o no hay SQL, devolvemos sin ejecutar query.
        if not sql_query or viz_type == "text":
            return {
                "answer": result.get("explanation", "Necesito más contexto."),
                "viz_type": "text",
                "title": result.get("title", "Respuesta"),
                "data": [],
                "columns": [],
            }

        print(f"⚡ Ejecutando SQL: {sql_query}")
        # Convert user_id to int if present, assuming get_conn handles the type or expects int
        uid_int = int(user_id) if user_id else None
        conn = get_conn(user_id=uid_int)
        df = pd.read_sql_query(sql_query, conn)
        conn.close()

        if df.empty:
            return {"answer": "No encontré datos con esa consulta, pero recuerda: " + result.get("explanation", ""), "viz_type": "none"}

        return {
            "answer": result.get("explanation", "Datos recuperados."),
            "viz_type": viz_type,
            "title": result.get("title", "Resultado"),
            "data": df.to_dict(orient="records"),
            "columns": list(df.columns),
            "sql": sql_query,
        }

    except Exception as e:
        print(f"❌ Error en Agente SQL: {e}")
        return {"answer": f"Error procesando tu solicitud: {e}", "viz_type": "error"}