import json
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


def process_file_stream(file_path: str, mime_type: str):
    """Parser universal con IA + auto-reparación de JSON."""
    print(f"🧠 IA Analizando: {file_path}")
    try:
        content_to_send = None
        is_native_file = False

        # Preparación
        if "pdf" in mime_type or file_path.endswith(".pdf"):
            is_native_file = True
        elif "csv" in mime_type or file_path.endswith(".csv") or "comma-separated" in mime_type:
            try:
                with open(file_path, "rb") as f:
                    raw = f.read()
                    try:
                        content_to_send = raw.decode("utf-8", errors="replace")
                    except Exception:
                        content_to_send = raw.decode("latin-1", errors="replace")
            except Exception as e:
                print(f"❌ No pude leer CSV: {e}")
                return []
        elif "sheet" in mime_type or "excel" in mime_type or file_path.endswith((".xlsx", ".xls")):
            try:
                df = pd.read_excel(file_path)
                content_to_send = df.to_markdown(index=False)
            except Exception as e:
                print(f"⚠️ Fallo lectura Excel: {e}")
                return []

        # Prompt
        extraction_prompt = """
        ACTÚA COMO: Data Engineer.
        OBJETIVO: Convertir este extracto bancario a JSON.

        REGLAS CRÍTICAS DE FORMATO:
        1. NO uses comillas simples (') en el JSON. Usa solo comillas dobles (").
        2. ESCAPA las comillas dobles que vengan DENTRO del texto (ej: "Pago \"Comercio\"" -> "Pago \\"Comercio\\"").
        3. Si el archivo es muy largo, prioriza devolver un JSON VÁLIDO y cerrado, aunque omitas filas finales. NO dejes el JSON abierto.

        SALIDA:
        [
          {"date": "YYYY-MM-DD", "amount": 0, "payee_name": "Nombre", "notes": "Desc"}
        ]
        """

        model = genai.GenerativeModel(AI_PARSER_MODEL)
        if is_native_file:
            uploaded_file = genai.upload_file(file_path, mime_type=mime_type)
            response = model.generate_content([extraction_prompt, uploaded_file])
        else:
            if not content_to_send:
                return []
            response = model.generate_content([extraction_prompt, sanitize_content(content_to_send)])

        raw_text = (response.text or "").strip()
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()

        try:
            transactions = json.loads(clean_json)
        except json.JSONDecodeError as e:
            transactions = fix_json_with_ai(clean_json, str(e))

        if not transactions:
            print("⚠️ No se pudieron extraer transacciones válidas.")
            return []

        print(f"✅ IA detectó {len(transactions)} transacciones.")
        return transactions

    except Exception as e:
        print(f"❌ Error Fatal: {e}")
        return []


# Compatibilidad
def process_file(file_path: str, mime_type: str = ""):
    return process_file_stream(file_path, mime_type)
