import json
import math
import pandas as pd
import google.generativeai as genai

AI_PARSER_MODEL = "gemini-2.5-flash"


def sanitize_content(text: str) -> str:
    """Limpia texto crudo para enviarlo al LLM."""
    if not text:
        return ""
    text = text.replace("\x00", "").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    # Permitimos archivos grandes (hasta ~1M chars) para no perder transacciones
    return "\n".join(lines)[:1000000]


def fix_json_with_ai(broken_json: str, error_msg: str):
    """Sub-agente: repara JSON inválido usando Gemini."""
    print(f"🔧 Intentando reparar JSON con IA... Error: {error_msg}")
    try:
        model = genai.GenerativeModel(AI_PARSER_MODEL)
        repair_prompt = f"""
        ACTÚA COMO: JSON Validator & Fixer.

        SITUACIÓN: El siguiente bloque de texto debería ser un JSON válido de transacciones bancarias, pero tiene errores de sintaxis.

        ERROR REPORTADO: {error_msg}

        TU TAREA:
        1. Analiza el JSON roto.
        2. Corrige la sintaxis para que sea parseable por Python json.loads.
        3. Si hay una cadena cortada al final, ciérrala y cierra el array ].
        4. Asegura que todas las claves y valores string tengan comillas dobles.

        INPUT ROTO:
        {broken_json[:50000]}

        SALIDA: ÚNICAMENTE EL JSON CORREGIDO.
        """
        response = model.generate_content(repair_prompt)
        text = (response.text or "").replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"❌ Falló la reparación automática: {e}")
        return []


def extract_with_llm(content: str | None = None, file_path: str | None = None, is_file: bool = False, mime_type: str | None = None):
    """Llama a Gemini para extraer movimientos de un fragmento o archivo."""
    model = genai.GenerativeModel(AI_PARSER_MODEL)
    prompt = """
    ACTÚA COMO: Data Engineer.
    TAREA: Extrae transacciones de este fragmento de datos.

    REGLAS:
    1. Devuelve SOLO un JSON array válido.
    2. Convierte fechas a 'YYYY-MM-DD'.
    3. Montos negativos para gastos/débitos.
    4. Campos requeridos: date, amount, payee_name, notes.
    5. NO inventes datos. Si el fragmento son solo encabezados, devuelve [].
    """
    try:
        if is_file:
            uploaded = genai.upload_file(file_path, mime_type=mime_type)
            response = model.generate_content([prompt, uploaded])
        else:
            response = model.generate_content([prompt, content or ""])
        text = (response.text or "").replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            return fix_json_with_ai(text, str(e))
    except Exception as e:
        print(f"⚠️ Error en lote LLM: {e}")
        return []


def process_file_stream(file_path: str, mime_type: str):
    """Parser universal con IA + auto-reparación, con chunking para archivos grandes."""
    print(f"🧠 IA Analizando archivo masivo: {file_path}")
    all_transactions: list = []
    try:
        mime_lower = (mime_type or "").lower()
        is_csv = "csv" in mime_lower or "comma-separated" in mime_lower or file_path.endswith(".csv")
        is_excel = any(x in mime_lower for x in ["sheet", "excel"]) or file_path.endswith((".xlsx", ".xls"))

        # A) CSV / EXCEL -> chunking de 50 filas
        if is_csv or is_excel:
            try:
                if is_excel:
                    df = pd.read_excel(file_path)
                else:
                    df = pd.read_csv(file_path, sep=None, engine="python", on_bad_lines="skip", encoding_errors="replace")
            except Exception as e:
                print(f"⚠️ Fallo lectura pandas, enviando texto crudo: {e}")
                try:
                    with open(file_path, "rb") as f:
                        raw = f.read()
                    text = sanitize_content(raw.decode("utf-8", errors="replace"))
                    return extract_with_llm(content=text, is_file=False)
                except Exception as e2:
                    print(f"❌ No pude leer archivo: {e2}")
                    return []

            total_rows = len(df)
            BATCH_SIZE = 50
            total_batches = math.ceil(total_rows / BATCH_SIZE) if total_rows else 0
            print(f"📊 Archivo tiene {total_rows} filas. Procesando en {total_batches} lotes de {BATCH_SIZE}.")

            for start in range(0, total_rows, BATCH_SIZE):
                chunk = df.iloc[start : start + BATCH_SIZE]
                chunk_text = chunk.to_markdown(index=False)
                print(f"   🔄 Lote {start} - {start + len(chunk)}")
                batch_txs = extract_with_llm(content=chunk_text, is_file=False)
                if batch_txs:
                    all_transactions.extend(batch_txs)

        # B) PDF u otro binario: envío nativo
        elif "pdf" in mime_lower or file_path.endswith(".pdf"):
            print("📄 Procesando PDF nativo...")
            all_transactions = extract_with_llm(file_path=file_path, is_file=True, mime_type=mime_type)

        else:
            # Fallback: texto plano
            try:
                with open(file_path, "rb") as f:
                    raw = f.read()
                text = sanitize_content(raw.decode("utf-8", errors="replace"))
                all_transactions = extract_with_llm(content=text, is_file=False)
            except Exception as e:
                print(f"⚠️ No pude leer el archivo: {e}")
                return []

        print(f"✅ EXTRACCIÓN TOTAL: {len(all_transactions)} movimientos recuperados.")
        return all_transactions
    except Exception as e:
        print(f"❌ Error Fatal Data Engine: {e}")
        return []


# Compatibilidad
def process_file(file_path: str, mime_type: str = ""):
    return process_file_stream(file_path, mime_type)
