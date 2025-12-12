import os
import json
import datetime
import time
import re
import asyncio
import threading
import secrets
from uuid import uuid4
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx
import email_ingest
import identity_manager
from briefing_agent import send_morning_briefing
from db_ops import ensure_account, insert_transactions, execute_query
from text_to_ui_agent import process_query
from onboarding_agent import process_onboarding
from message_queue import enqueue_message, worker as mq_worker
from backup_manager import run_backup
from tools import (
    TOOLS_SCHEMA,
    get_financial_audit,
    create_category_tool,
    categorize_payees_tool,
    create_account_tool,
    find_and_import_history_tool,
    complete_onboarding_tool,
    confirm_import_tool,
    generate_spending_chart_tool,
)
from database import init_db, get_user_context, save_user_context, get_conn, save_pending_data, get_pending_data
from data_engine import process_file_universal
from profile_manager import get_user_profile, update_financial_goals

# Inicialización
app = FastAPI(title="AFI Brain v7.0 God Mode")
scheduler = AsyncIOScheduler()

# Configurar Gemini
GENAI_KEY = os.getenv("GOOGLE_API_KEY")
if not GENAI_KEY:
    print("⚠️ CRÍTICO: No se encontró GOOGLE_API_KEY en .env")
else:
    genai.configure(api_key=GENAI_KEY)

# Configuración Push
ADMIN_PHONE = os.getenv("ADMIN_PHONE")
WHATSAPP_PUSH_URL = os.getenv("WHATSAPP_PUSH_URL", "http://afi-whatsapp:3000/send-message")
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://afi-whatsapp:3000")

# Modelos Gemini (Cerebro Dual)
MODEL_SMART = "gemini-2.5-pro"   # Onboarding / Sherlock / Análisis profundo
MODEL_FAST = "gemini-2.5-flash"  # Operación diaria / respuestas rápidas

# Memoria de chat agéntico
chat_history = []
# Buffers para uploads múltiples
upload_buffers: dict[str, list] = {}
# Generaciones de debounce para reiniciar la espera por usuario
debounce_generation: dict[str, int] = {}

# Config sesión/OTP persistente
OTP_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 3600
# Desactivar WatchFiles: no usar reload en producción; este flag evita ruido si se activa en uvicorn.
# Inicializar DB
init_db()


class WhatsAppMessage(BaseModel):
    from_user: str
    body: str
    hasMedia: bool
    timestamp: int
    media_path: str | None = None
    media_mime: str | None = None


class OTPRequest(BaseModel):
    phone: str


class OTPVerify(BaseModel):
    phone: str
    code: str


class ChatQuery(BaseModel):
    question: str
    token: str | None = None
    phone: str | None = None
    history: list[dict] | None = None


def _debounce_worker(phone: str, gen: int):
    """Worker en hilo: espera ventana y procesa si la generación sigue vigente."""
    # Procesar casi inmediato
    time.sleep(0.1)
    if debounce_generation.get(phone) != gen:
        return
    try:
        asyncio.run(process_buffered_files(phone))
    except Exception as e:
        print(f"🔥 Error en timer de buffer para {phone}: {e}")


async def check_emails():
    """Escaneo periódico de correos bancarios (Omnicanalidad)."""
    from email_agent import check_emails as run_email_check
    print("📧 Scheduler: Iniciando escaneo de correos...")
    try:
        # Ejecutar en un hilo para no bloquear el loop principal ni las peticiones HTTP.
        await asyncio.to_thread(run_email_check)
    except Exception as e:
        print(f"❌ Error crítico en check_emails: {e}")


def _resolve_user_id(phone: str) -> int | None:
    try:
        row = execute_query("SELECT id FROM users WHERE phone = %s", (phone,), fetch_one=True)
        return row[0] if row else None
    except Exception as e:
        print(f"⚠️ Error resolving user_id for {phone}: {e}")
        return None


def execute_function(name, args, user_id=None):
    """Normaliza argumentos de llamada de herramienta y despacha a la implementación."""
    def _to_python(val):
        # Convierte objetos protobuf (MapComposite/RepeatedComposite) a tipos nativos.
        if isinstance(val, dict):
            return {k: _to_python(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return [_to_python(v) for v in val]
        try:
            # RepeatedComposite itera pero no es list
            if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
                return [_to_python(v) for v in list(val)]
        except Exception:
            pass
        return val

    py_args = {}
    try:
        py_args = {k: _to_python(v) for k, v in args.items()}
    except Exception:
        py_args = {}

    if name == "get_financial_audit":
        return get_financial_audit()
    if name == "create_category_tool":
        return create_category_tool(py_args.get("name"), py_args.get("group", "Gastos Variables"))
    if name == "categorize_payees_tool":
        keywords = py_args.get("keywords_list") or []
        if not isinstance(keywords, list):
            try:
                keywords = list(keywords)
            except Exception:
                keywords = [str(keywords)]
        return categorize_payees_tool(py_args.get("category_name"), keywords)
    if name == "create_account_tool":
        return create_account_tool(py_args.get("account_name"), py_args.get("account_type", "checking"), user_id=user_id)
    if name == "find_and_import_history_tool":
        return find_and_import_history_tool(py_args.get("account_name"))
    if name == "complete_onboarding_tool":
        return complete_onboarding_tool(py_args.get("summary"))
    if name == "confirm_import_tool":
        return confirm_import_tool(py_args.get("target_account_name"), user_id=user_id)
    if name == "generate_spending_chart_tool":
        return generate_spending_chart_tool(py_args.get("period", "current_month"), user_id=user_id)
    return "Error: Tool not found"


def get_system_instruction(file_summary: str, current_mode: str, wisdom_context: str, is_admin_incomplete: bool) -> str:
    """Construye el prompt del sistema con idioma forzado y capacidades multimodales."""
    if is_admin_incomplete:
        system_instruction = """
        Eres AFI, el CFO Personal Inteligente.
        Estás hablando con un usuario NUEVO (DB vacía).
        
        TU OBJETIVO ÚNICO: Llenar el sistema de datos REALES.
        
        PROTOCOLO:
        1. NO hagas preguntas aburridas ("¿En qué gastas?").
        2. PIDE EVIDENCIA: "Hola. Para organizar tus finanzas, necesito datos. **Envíame ahora mismo tus extractos bancarios (PDF/Excel) o fotos de facturas**."
        3. Si el usuario envía archivos, el sistema los procesará. Tú solo guía.
        4. Si el sistema dice "Cargué X movimientos", confirma que las cuentas se hayan creado.
        
        TONO: Ejecutivo, Directo, "Cero Fricción".
        """
    elif current_mode == "SHERLOCK":
        # This block is now effectively dead code, but keeping it for clarity that SHERLOCK logic is handled by is_admin_incomplete
        system_instruction = f"""
Eres AFI, el CFO Personal y Asesor Patrimonial.

IDIOMA OBLIGATORIO:
Habla EXCLUSIVAMENTE en Español Latinoamericano.
Usa términos locales (pesos, 'tanquear', 'mercado') si aplica.
Nunca respondas en inglés.

MEMORIA DEL USUARIO:
{file_summary[:6000]}

ESTADO ACTUAL: {current_mode}

CONOCIMIENTO FINANCIERO (LIBROS):
{wisdom_context if wisdom_context else "Sin citas disponibles para esta consulta."}

CAPACIDADES:
- Puedes ver imágenes (recibos, facturas). Extrae: Fecha, Comercio, Total, Categoría.
- Puedes escuchar audios. Transcribe mentalmente y ejecuta la intención financiera.

INSTRUCCIONES:
1. Usa únicamente la memoria que recibes arriba; si está vacía, entrevista para obtener datos.
2. Si hay texto en CONOCIMIENTO FINANCIERO, úsalo para responder y cita la fuente entre corchetes.
"""
    else:
        system_instruction = f"""
Eres AFI, el CFO Personal y Asesor Patrimonial.

IDIOMA OBLIGATORIO:
Habla EXCLUSIVAMENTE en Español Latinoamericano.
Usa términos locales (pesos, 'tanquear', 'mercado') si aplica.
Nunca respondas en inglés.

MEMORIA DEL USUARIO:
{file_summary[:6000]}

ESTADO ACTUAL: {current_mode}

CONOCIMIENTO FINANCIERO (LIBROS):
{wisdom_context if wisdom_context else "Sin citas disponibles para esta consulta."}

CAPACIDADES:
- Puedes ver imágenes (recibos, facturas). Extrae: Fecha, Comercio, Total, Categoría.
- Puedes escuchar audios. Transcribe mentalmente y ejecuta la intención financiera.

INSTRUCCIONES:
1. Usa únicamente la memoria que recibes arriba; si está vacía, entrevista para obtener datos.
2. Si hay texto en CONOCIMIENTO FINANCIERO, úsalo para responder y cita la fuente entre corchetes.
"""
    return system_instruction


def retrieve_wisdom(query: str, top_k: int = 3) -> str:
    """Busca pasajes relevantes en financial_wisdom usando pgvector."""
    if not query:
        return ""
    try:
        resp = genai.embed_content(model="models/text-embedding-004", content=query, task_type="retrieval_query")
        embedding = None
        if isinstance(resp, dict):
            embedding = resp.get("embedding")
        else:
            try:
                embedding = resp["embedding"]
            except Exception:
                embedding = None
        if not embedding:
            return ""
        vec_literal = "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content, source FROM financial_wisdom ORDER BY embedding <-> %s::vector LIMIT %s",
                    (vec_literal, top_k),
                )
                rows = cur.fetchall()
                if not rows:
                    return ""
                snippets = []
                for content, source in rows:
                    source_name = source or "desconocido"
                    snippets.append(f"[{source_name}] {content}")
                return "\n\n".join(snippets)
    except Exception as e:
        print(f"⚠️ RAG search failed: {e}")
        return ""


def _extract_json_dict(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    cleaned = text.strip()
    if cleaned.startswith("```"):
        try:
            return json.loads(cleaned.strip("`").strip())
        except Exception:
            pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


def _normalize_amount_value(value, force_expense: bool = True):
    try:
        amount = float(value)
    except Exception:
        return None
    if force_expense and amount > 0:
        amount = -amount
    return amount


def _ensure_account_sync(account_name: str) -> int | None:
    name = (account_name or "").strip()
    if not name:
        return None
    try:
        return ensure_account(name)
    except Exception as e:
        print(f"⚠️ No se pudo asegurar cuenta {name}: {e}")
        return None


def _ingest_voice_transaction(structured: dict) -> str:
    if not structured:
        return "⚠️ No pude entender la nota de voz."

    account_name = (
        structured.get("account")
        or structured.get("account_name")
        or structured.get("wallet")
        or "Cuenta Voz"
    )
    payee = structured.get("payee") or structured.get("merchant") or "Gasto de voz"
    date_str = structured.get("date") or datetime.date.today().isoformat()
    amount_value = _normalize_amount_value(structured.get("amount"), force_expense=True)
    if amount_value is None or amount_value == 0:
        return "⚠️ No pude extraer el monto del audio."
    notes = structured.get("notes") or structured.get("transcription") or "Nota de voz registrada automáticamente."

    account_id = _ensure_account_sync(account_name)
    if not account_id:
        return f"⚠️ No pude asegurar la cuenta '{account_name}' para registrar el gasto."

    tx_payload = {
        "date": date_str,
        "amount": amount_value,
        "description": str(payee)[:200],
        "import_source": "voice_flash",
        "category": structured.get("category"),
    }

    try:
        inserted = insert_transactions(account_id, [tx_payload], import_source="voice_flash")
        if inserted == 0:
            return "⚠️ No pude registrar el gasto en la bóveda."
        amount_display = abs(amount_value)
        return f"✅ Registré ${amount_display:,.0f} en {payee} ({account_name})."
    except Exception as e:
        print(f"❌ Error importando gasto de voz: {e}")
        return f"⚠️ No pude registrar el gasto en {account_name}. Intenta de nuevo por texto."


def _normalize_phone(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _store_otp(phone: str, code: str, expires_at: float) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO otps (phone, code, expires_at)
                VALUES (%s, %s, to_timestamp(%s))
                ON CONFLICT (phone) DO UPDATE SET code = EXCLUDED.code, expires_at = EXCLUDED.expires_at;
                """,
                (phone, code, expires_at),
            )


def _validate_otp(phone: str, code: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, EXTRACT(EPOCH FROM expires_at) FROM otps WHERE phone = %s;",
                (phone,),
            )
            row = cur.fetchone()
            if not row:
                return False
            stored_code, exp_ts = row
            if time.time() > float(exp_ts):
                cur.execute("DELETE FROM otps WHERE phone = %s;", (phone,))
                return False
            if stored_code != code:
                return False
            cur.execute("DELETE FROM otps WHERE phone = %s;", (phone,))
            return True


def _create_session(phone: str) -> tuple[str, int]:
    token = uuid4().hex
    expires_at = time.time() + SESSION_TTL_SECONDS
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (token, phone, expires_at)
                VALUES (%s, %s, to_timestamp(%s))
                ON CONFLICT (token) DO UPDATE SET phone = EXCLUDED.phone, expires_at = EXCLUDED.expires_at;
                """,
                (token, phone, expires_at),
            )
            # Limpieza básica
            cur.execute("DELETE FROM sessions WHERE expires_at < NOW();")
    return token, SESSION_TTL_SECONDS


def _validate_session_token(token: str | None) -> str | None:
    if not token:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT phone FROM sessions WHERE token = %s AND expires_at > NOW();",
                (token,),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            return None


@app.post("/auth/request-otp")
async def request_otp(payload: OTPRequest):
    phone = _normalize_phone(payload.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Número de teléfono requerido.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = time.time() + OTP_TTL_SECONDS
    _store_otp(phone, code, expires_at)
    try:
        await send_push_message(phone, f"Tu código de acceso AFI es: {code}")
    except Exception as e:
        print(f"⚠️ No se pudo enviar OTP a {phone}: {e}")
        raise HTTPException(status_code=500, detail="No se pudo enviar el código.")
    return {"status": "ok", "expires_in": OTP_TTL_SECONDS}


@app.post("/auth/verify-otp")
async def verify_otp(payload: OTPVerify):
    phone = _normalize_phone(payload.phone)
    code = (payload.code or "").strip()
    if not phone or not code:
        raise HTTPException(status_code=400, detail="Teléfono y código son obligatorios.")
    valid = _validate_otp(phone, code)
    if not valid:
        raise HTTPException(status_code=401, detail="Código incorrecto o expirado.")
    token, ttl = _create_session(phone)
    try:
        await send_push_message(phone, "✅ Acceso autorizado. Bienvenido a AFI.")
    except Exception as e:
        print(f"⚠️ No se pudo confirmar OTP por WhatsApp: {e}")
    return {"status": "authenticated", "token": token, "expires_in": ttl}


@app.post("/chat/query")
async def chat_query(payload: ChatQuery):
    if not payload.question:
        raise HTTPException(status_code=400, detail="Pregunta requerida.")
    phone = None
    # Validar sesión si se envía token
    if payload.token:
        phone_validated = _validate_session_token(payload.token)
        if not phone_validated:
            raise HTTPException(status_code=401, detail="Sesión expirada o inválida.")
        phone = phone_validated
    
    # --- INTERCEPCIÓN ONBOARDING ---
    if phone:
        # Ejecutar en hilo aparte para no bloquear
        onboarding_reply = await asyncio.to_thread(process_onboarding, payload.question, phone)
        if onboarding_reply:
            return {
                "answer": onboarding_reply,
                "viz_type": "text", # El onboarding es puramente conversacional
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "data": [],
                "columns": []
            }
    # -------------------------------

    result = await asyncio.to_thread(process_query, payload.question, phone or payload.phone, payload.history or [])
    result["timestamp"] = datetime.datetime.utcnow().isoformat()
    return result


def _extract_voice_transaction(uploaded_file, context: str):
    prompt = f"""
Eres AFI, CFO personal.
Contexto del usuario: "{context}"
Transcribe la nota de voz y extrae el gasto.
Devuelve SOLO JSON con:
- amount: número (gasto en negativo si no se indica signo)
- payee: comercio o concepto
- account: cuenta o billetera mencionada
- date: YYYY-MM-DD (usa la fecha de hoy por defecto)
- notes: detalle breve
- transcription: transcripción corta

Ejemplo de salida:
{{"amount": -20000, "payee": "Taxi", "account": "Nequi", "date": "2024-11-19", "notes": "viaje aeropuerto", "transcription": "me gasté 20 mil en taxi"}}
"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content([prompt, uploaded_file])
    raw_text = response.text or ""
    parsed = _extract_json_dict(raw_text)
    if parsed and isinstance(parsed, dict) and not parsed.get("date"):
        parsed["date"] = datetime.date.today().isoformat()
    return parsed, raw_text.strip()


def process_multimodal_request(user_text: str, media_path: str, media_mime: str, system_instruction: str, phone: str) -> str:
    """Procesa audio/imagen/documentos con Gemini 2.5 Flash, corrigiendo MIME y esperando procesamiento."""
    print(f"👁️ Procesando archivo: {media_path} ({media_mime})")
    if not os.path.exists(media_path):
        return f"⚠️ Error técnico: El archivo no se encuentra en {media_path}. Verifica volúmenes."

    # Caso documento (CSV/Excel): procesar localmente y guardar en limbo
    mime_lower = (media_mime or "").lower()
    if (
        any(x in mime_lower for x in ["csv", "comma-separated", "sheet", "excel", "ms-excel"])
        or media_path.endswith((".csv", ".xlsx", ".xls"))
        or (user_text and ".csv" in user_text.lower())
    ):
        print("📄 Documento financiero recibido.")
        transactions = process_file_stream(media_path, media_mime or "")
        if not transactions:
            return "❌ Recibí el archivo pero no pude leer columnas de Fecha y Monto. ¿Es un formato estándar?"
        existing = get_pending_data(phone) or []
        if not isinstance(existing, list):
            try:
                existing = list(existing)
            except Exception:
                existing = []
        combined = existing + transactions
        save_pending_data(phone, combined)
        count_new = len(transactions)
        total_pending = len(combined)
        return f"""✅ Archivo procesado.
Añadí **{count_new} movimientos**.
📊 Total acumulado en cola: **{total_pending}** movimientos.
Sigue enviando archivos si tienes más.
Cuando quieras cargar, dime: "Cargar a la cuenta X". """

    mime_to_use = media_mime or "application/octet-stream"
    if "ogg" in mime_to_use or media_path.endswith(".ogg"):
        mime_to_use = "audio/ogg"
    elif "jpeg" in mime_to_use or "jpg" in mime_to_use:
        mime_to_use = "image/jpeg"

    try:
        uploaded_file = genai.upload_file(media_path, mime_type=mime_to_use)
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(0.25)
            uploaded_file = genai.get_file(uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            return "⚠️ Google no pudo procesar el formato del archivo."

        # OPTIMIZACIÓN FLASH (Solo Audio)
        is_audio = "audio" in mime_to_use or "ogg" in mime_to_use
        
        if is_audio:
            structured, raw_voice = _extract_voice_transaction(uploaded_file, user_text)
            if structured:
                return _ingest_voice_transaction(structured)
            return raw_voice or "⚠️ Audio mudo."

        multimodal_prompt = f"""
CONTEXTO USUARIO: "{user_text}"
ARCHIVO: Analiza este audio/imagen.
- Si es AUDIO: Transcribe y extrae intención (Gasto, Consulta).
- Si es IMAGEN: Extrae datos del recibo.

ACCIÓN: Ejecuta la herramienta necesaria o responde.
"""

        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_instruction, tools=TOOLS_SCHEMA)
        response = model.generate_content([multimodal_prompt, uploaded_file])
        return response.text if response else "⚠️ No se obtuvo respuesta del modelo."

    except Exception as e:
        print(f"❌ Error multimodal: {e}")
        return "⚠️ Error procesando el archivo multimedia. Por favor intenta con texto por ahora."


async def send_media_message(phone: str, file_path: str, caption: str = ""):
    """Envía multimedia vía endpoint /send-media."""
    try:
        async with httpx.AsyncClient() as client:
             # Nota: path debe ser accesible por el contenedor afi-whatsapp (volumen compartido /app/data/media)
             # file_path interno en afi-core: /app/data/media/xyz.png
             # file_path en afi-whatsapp: /app/data/media/xyz.png (si volúmenes coinciden)
             await client.post(f"{BRIDGE_URL}/send-media", json={
                 "phone": phone,
                 "filePath": file_path,
                 "caption": caption
             })
    except Exception as e:
        print(f"❌ Error enviando media a {phone}: {e}")


def ai_router(text: str, user_context: dict) -> str:
    """Bucle agéntico con Gemini y function-calling."""
    global chat_history
    print(f"🧠 [DEBUG] Enviando a Gemini: {text}")
    try:
        phone = user_context.get("phone") or user_context.get("from_user")
        
        # Resolver User ID para RLS
        user_id = _resolve_user_id(phone) if phone else None

        # 1. RECUPERAR IDENTIDAD Y MEMORIA
        user_profile = get_user_profile(phone)
        state = get_user_context(phone)  # Memoria técnica (vectores, csv)

        file_summary = state.get("file_context") if state else ""
        current_mode = state.get("mode") if state else "NORMAL"

        admin_incomplete = (
            user_profile
            and user_profile.get("role") == "admin"
            and user_profile.get("status") == "incomplete"
        )

        # 2. LOGICA DE MODO (SHERLOCK VS CFO)
        # Si es el Admin, no tiene resumen de archivos y su perfil está incompleto -> MODO SHERLOCK
        if admin_incomplete:
            file_summary = ""
            current_mode = "SHERLOCK"
        else:
            # MODO NORMAL (CFO) - Usa la memoria y herramientas existentes
            current_mode = current_mode or "NORMAL"

            # Autorecuperación de contexto (Si la DB está vacía pero hay archivo)
            if not admin_incomplete and not file_summary:
                print("🔍 Contexto vacío. Intentando leer auditoría física...")
                try:
                    raw_audit = get_financial_audit()  # Lee CSV
                    if raw_audit and "total_spent" in raw_audit and "Error" not in raw_audit:
                        file_summary = raw_audit
                        current_mode = "ONBOARDING"
                        save_user_context(phone, file_summary=raw_audit, mode="ONBOARDING")
                except Exception as e:
                    print(f"⚠️ No hay CSV o error lectura: {e}")

        wisdom_context = retrieve_wisdom(text)
        system_instruction = get_system_instruction(file_summary, current_mode, wisdom_context, admin_incomplete)

        # 2b. Selección dinámica de modelo
        if current_mode in ("SHERLOCK", "ONBOARDING"):
            target_model = MODEL_SMART
            print(f"🧠 Modo Arquitecto Activado ({target_model})")
        else:
            target_model = MODEL_FAST
            print(f"⚡ Modo Operativo Activado ({target_model})")

        # 3. INVOCAR GEMINI
        model = genai.GenerativeModel(
            target_model,
            tools=TOOLS_SCHEMA,
            system_instruction=system_instruction,
        )
        chat = model.start_chat(history=chat_history)
        response = chat.send_message(text)
        print(f"🧠 [DEBUG] Respuesta Gemini Cruda: {response}")

        while True:
            tool_call = None
            for part in response.parts:
                if part.function_call:
                    tool_call = part.function_call
                    break
            if not tool_call:
                break

            print(f"🔧 [DEBUG] Gemini quiere usar herramienta: {tool_call.name} args: {tool_call.args}")
            # Feedback inmediato al usuario sobre trabajo en curso
            try:
                if phone:
                    asyncio.create_task(enqueue_message(phone, "⏳ Procesando cambios en la Bóveda..."))
            except Exception as e:
                print(f"⚠️ No se pudo enviar feedback inmediato: {e}")

            try:
                # PASS USER_ID TO TOOLS
                tool_result = execute_function(tool_call.name, tool_call.args, user_id=user_id)
            except Exception as e:
                tool_result = f"Error ejecutando herramienta {tool_call.name}: {e}"

            print(f"🔧 [DEBUG] Resultado herramienta: {tool_result}")
            response = chat.send_message(
                genai.protos.Content(
                    parts=[
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_call.name, response={"result": tool_result}
                            )
                        )
                    ]
                )
            )

        chat_history = chat.history
        print(f"🧠 [DEBUG] Texto Final generado: {getattr(response, 'text', None)}")
        if not response or not response.text:
            return "⚠️ Error: Gemini generó una respuesta vacía."
        return response.text.strip()
    except Exception as e:
        print(f"🔥 Error en AI router: {e}")
        return "Mi conexión neuronal falló. Intenta de nuevo en un momento."


# --- Buffer asíncrono de archivos (debounce 4s) ---
async def process_buffered_files(phone: str):
    files = upload_buffers.pop(phone, [])
    if not files: return

    # Feedback Inmediato (UX)
    await send_push_message(phone, "🧐 Recibido. Estoy leyendo tus documentos con Gemini Pro... Dame unos segundos.")

    all_txs = []
    accounts_detected = set()

    # Procesar en paralelo o serie (Serie es más seguro para no saturar API)
    for f in files:
        txs = await asyncio.to_thread(process_file_universal, f['path'], f['mime'])
        if txs:
            all_txs.extend(txs)
            # Recolectar pistas de qué bancos encontró
            for t in txs:
                if t.get('account_hint'):
                    accounts_detected.add(t['account_hint'])

    # Guardar en Limbo (DB)
    save_pending_data(phone, all_txs)
    
    # Reporte Inteligente
    total = sum(t['amount'] for t in all_txs)
    bancos_str = ", ".join(accounts_detected) if accounts_detected else "tus cuentas"
    
    msg = f"""
    ✅ **Análisis Completado**
    Procesé {len(files)} documentos.
    
    📄 **Movimientos:** {len(all_txs)}
    🏦 **Bancos Detectados:** {bancos_str}
    💰 **Neto:** ${total:,.0f}
    
    Para terminar, confirma:
    * **"Cargar a Nubank"**
    * **"Cargar a Bancolombia"**
    * O dime: **"Crear cuentas y cargar"** (Si es la primera vez).
    """
    
    target_phone = os.getenv("ADMIN_PHONE", phone)
    await send_push_message(target_phone, msg)


async def send_push_message(phone: str, text: str):
    """Encola mensaje para envío anti-ban."""
    try:
        await enqueue_message(phone, text)
    except Exception as e:
        print(f"❌ Error encolando mensaje a {phone}: {e!r}")


@app.get("/")
def health_check():
    return {"status": "online", "system": "AFI Core"}


@app.post("/webhook/whatsapp")
async def receive_message(request: Request):
    data = await request.json()
    user_phone = data.get("from_user")
    body = data.get("body", "")
    print(f"📥 Brain recibió de {user_phone}: {body} | hasMedia={data.get('hasMedia')} media={data.get('media')}")

    user = identity_manager.get_user_session(user_phone or "")
    if not user:
        return {"reply": "No estás autorizado para usar AFI. Solicita acceso al administrador."}

    # Enriquecer contexto con phone para feedback en tools
    user = dict(user)
    user["phone"] = user_phone
    user["from_user"] = user_phone

    reply_text = ""

    # Memoria persistente para multimodal y texto
    state = get_user_context(user_phone)
    file_summary = state.get("file_context") if state else ""
    current_mode = state.get("mode") if state else "NORMAL"

    if not file_summary:
        try:
            raw_audit = get_financial_audit()
            if raw_audit and "total_spent" in raw_audit and "Error" not in raw_audit:
                file_summary = raw_audit
                current_mode = "ONBOARDING"
                save_user_context(user_phone, file_summary=raw_audit, mode="ONBOARDING")
        except Exception as e:
            print(f"⚠️ No hay CSV o error lectura: {e}")

    # Consolidar media (nuevo o legacy)
    media_payload = data.get("media")
    if not media_payload and data.get("media_path"):
        media_payload = {"path": data.get("media_path"), "mime": data.get("media_mime")}

    # --- Buffer de archivos (CSV/Excel/PDF) con debounce 4s ---
    if data.get("hasMedia") and media_payload and media_payload.get("path"):
        mime_raw = media_payload.get("mime") or ""
        mime = mime_raw.lower()
        filename_lower = (media_payload.get("filename") or "").lower()
        path_lower = media_payload.get("path", "").lower()
        is_doc = any(x in mime for x in ["csv", "comma-separated", "sheet", "excel", "ms-excel", "pdf"]) or filename_lower.endswith((".csv", ".xlsx", ".xls", ".pdf")) or path_lower.endswith((".csv", ".xlsx", ".xls", ".pdf"))
        if is_doc:
            # Override mime_raw for CSV files to ensure compatibility with Gemini's File API
            if any(x in mime for x in ["csv", "comma-separated"]) or filename_lower.endswith(".csv") or path_lower.endswith(".csv"):
                mime_raw = "text/csv"
            filename = media_payload.get("filename") or media_payload.get("path")
            print(f"⏳ Buffering archivo: {filename}")

            upload_buffers.setdefault(user_phone, []).append({"path": media_payload.get("path"), "mime": mime_raw, "filename": media_payload.get("filename")})
            # Procesar de inmediato (sin esperar debounce)
            await process_buffered_files(user_phone)
            return {"status": "processed", "message": None}

        # Otros media (audio/imagen) -> procesar normal
        wisdom_context = retrieve_wisdom(body, top_k=3)
        user_profile = get_user_profile(user_phone)
        admin_incomplete = (
            user_profile
            and user_profile.get("role") == "admin"
            and user_profile.get("status") == "incomplete"
        )

        system_instruction = get_system_instruction(file_summary or "", current_mode or "NORMAL", wisdom_context, admin_incomplete)
        reply_text = await asyncio.to_thread(
            process_multimodal_request,
            body,
            media_payload.get("path"),
            media_payload.get("mime") or "application/octet-stream",
            system_instruction,
            user_phone,
        )
    else:
        # Flujo Texto Normal
        reply_text = await asyncio.to_thread(ai_router, body, user)

    print(f"🧠 Gemini responde: {str(reply_text)[:80]}...")

    if reply_text:
        try:
            target_phone = user_phone or os.getenv("ADMIN_PHONE")
            print(f"📤 Enviando mensaje a {target_phone} (origen: {user_phone})...")
            
            if reply_text.startswith("[MEDIA]"):
                media_path = reply_text.replace("[MEDIA]", "").strip()
                await send_media_message(target_phone, media_path, caption="📊 Aquí tienes tu gráfico.")
            else:
                await enqueue_message(target_phone, reply_text)
                
            print("✅ Mensaje en cola para entrega.")
        except Exception as e:
            print(f"❌ Error encolando envío a WhatsApp: {e}")

    return {"status": "processed"}


@app.on_event("startup")
async def start_scheduler():
    try:
        # Worker anti-ban
        asyncio.create_task(mq_worker())

        scheduler.add_job(send_morning_briefing, CronTrigger(hour=7, minute=0))
        
        # PRUEBA INMEDIATA (En 2 minutos para validación de sprint)
        run_date = datetime.datetime.now() + datetime.timedelta(minutes=2)
        scheduler.add_job(send_morning_briefing, 'date', run_date=run_date)
        print(f"🧪 Prueba de Briefing programada para: {run_date}")

        # Backup diario 03:00 AM
        scheduler.add_job(run_backup, CronTrigger(hour=3, minute=0))

        # Omnicanalidad activada
        scheduler.add_job(check_emails, CronTrigger(minute="*/15"))
        scheduler.start()
        print("⏳ Scheduler iniciado: AFI ahora tiene vida propia.")
    except Exception as e:
        print(f"⚠️ Error iniciando scheduler: {e}")
