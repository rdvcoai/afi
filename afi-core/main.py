import os
import json
import datetime
import time
import asyncio
import threading
from fastapi import FastAPI, Request
from pydantic import BaseModel
import google.generativeai as genai
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx
import email_ingest
import identity_manager
from tools import (
    TOOLS_SCHEMA,
    get_financial_audit,
    create_category_tool,
    categorize_payees_tool,
    create_account_tool,
    find_and_import_history_tool,
    import_history_from_file_tool,
    complete_onboarding_tool,
    confirm_import_tool,
)
from database import init_db, get_user_context, save_user_context, get_conn, save_pending_data, get_pending_data
from data_engine import process_file_stream
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


def _debounce_worker(phone: str, gen: int):
    """Worker en hilo: espera ventana y procesa si la generación sigue vigente."""
    time.sleep(0.5)
    if debounce_generation.get(phone) != gen:
        return
    try:
        asyncio.run(process_buffered_files(phone))
    except Exception as e:
        print(f"🔥 Error en timer de buffer para {phone}: {e}")


async def morning_briefing():
    """Briefing diario 7:00 AM."""
    print("⏰ Generando Morning Briefing con IA...")
    try:
        today = datetime.date.today()
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"""
Eres AFI, mi gestor de patrimonio. Hoy es {today.strftime('%A %d de %B')}.
Genera un 'Morning Briefing' corto (máx 3 párrafos) estilo Mr. Money Mustache / Ramit Sethi.
"""
        response = model.generate_content(prompt)
        briefing_text = response.text
        phone = ADMIN_PHONE
        if not phone:
            print("⚠️ No ADMIN_PHONE configurado.")
            return
        async with httpx.AsyncClient() as client:
            await client.post(WHATSAPP_PUSH_URL, json={"phone": phone, "message": briefing_text}, timeout=20.0)
            print("✅ Morning Briefing enviado.")
    except Exception as e:
        print(f"🔥 Error en Morning Briefing: {e}")


async def check_emails():
    """Escaneo periódico de correos bancarios."""
    print("📧 Scaneando correos bancarios...")
    try:
        # Ejecutar en un hilo para no bloquear el loop principal ni las peticiones HTTP.
        await asyncio.to_thread(email_ingest.process_emails)
    except Exception as e:
        print(f"❌ Error crítico en check_emails: {e}")


def execute_function(name, args):
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
        return create_account_tool(py_args.get("account_name"), py_args.get("account_type", "checking"))
    if name == "find_and_import_history_tool":
        return find_and_import_history_tool(py_args.get("account_name"))
    if name == "import_history_from_file_tool":
        # aceptar account_name o account_id como alias
        return import_history_from_file_tool(
            account=py_args.get("account_name") or py_args.get("account_id"),
            file_name_in_server=py_args.get("file_name_in_server") or py_args.get("file_name") or py_args.get("file"),
        )
    if name == "complete_onboarding_tool":
        return complete_onboarding_tool(py_args.get("summary"))
    if name == "confirm_import_tool":
        return confirm_import_tool(py_args.get("target_account_name"))
    return "Error: Tool not found"


def get_system_instruction(file_summary: str, current_mode: str, wisdom_context: str) -> str:
    """Construye el prompt del sistema con idioma forzado y capacidades multimodales."""
    return f"""
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
1. Tu conocimiento sobre las finanzas de Diego viene EXCLUSIVAMENTE de la sección 'MEMORIA' de arriba. Úsala.
2. Si el estado es ONBOARDING y Diego saluda, preséntale el hallazgo más grande de la memoria.
3. Si hay texto en CONOCIMIENTO FINANCIERO, úsalo para responder y cita la fuente entre corchetes.
4. Si la memoria está vacía, inicia una entrevista para recolectar datos.
"""


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
                    "SELECT content, metadata FROM financial_wisdom ORDER BY embedding <-> %s::vector LIMIT %s",
                    (vec_literal, top_k),
                )
                rows = cur.fetchall()
                if not rows:
                    return ""
                snippets = []
                for content, metadata in rows:
                    source = "desconocido"
                    try:
                        if isinstance(metadata, str):
                            meta = json.loads(metadata)
                        else:
                            meta = metadata or {}
                        source = meta.get("source", source)
                    except Exception:
                        pass
                    snippets.append(f"[{source}] {content}")
                return "\n\n".join(snippets)
    except Exception as e:
        print(f"⚠️ RAG search failed: {e}")
        return ""


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
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            return "⚠️ Google no pudo procesar el formato del archivo."

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


def ai_router(text: str, user_context: dict) -> str:
    """Bucle agéntico con Gemini y function-calling."""
    global chat_history
    print(f"🧠 [DEBUG] Enviando a Gemini: {text}")
    try:
        phone = user_context.get("phone") or user_context.get("from_user")

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
            system_instruction = """
Eres AFI, un Arquitecto Financiero Privado de alto nivel.
Estás iniciando la relación con tu cliente. NO ASUMAS NADA. Tu trabajo es descubrir su realidad financiera.

OBJETIVO: Construir el "Mapa de Flujo de Dinero" del usuario.

PROTOCOLO DE ENTREVISTA (Conversacional, no interrogatorio):

1. MODELO MENTAL (La Estrategia):
   - Pregunta clave: "¿Cómo te gusta operar tu dinero? ¿Eres 'Totalero' (todo a Tarjeta de Crédito para ganar puntos y pagar a fin de mes) o prefieres usar Débito/Efectivo?"
   - Por qué importa: Si usa TC, las transferencias a la tarjeta NO son gastos, son pagos.

2. EL MAPA DE CUENTAS (La Infraestructura):
   - Identifica la cuenta "Hub" (ingresos) y las cuentas "Spoke" (gastos).
   - Pregunta: "¿En qué banco recibes tus ingresos principales y qué otras cuentas o billeteras usas?"

3. EL DOLOR (Prioridades):
   - Pregunta: "¿Tienes alguna meta urgente (viaje, compra) o alguna deuda que te quite el sueño?"

REGLA DE ORO:
- Si el usuario subió un CSV, analízalo PERO confirma tus sospechas con él. "Veo muchos movimientos en Nubank, ¿esa es tu tarjeta principal?"
- Habla siempre en Español Latinoamericano.
- HERRAMIENTA ESPECIAL ADMIN: Puedes leer archivos en /app/data/csv. Si el usuario te pide cargar historia (ej: Nubank), pregunta el nombre del archivo o sugiérelo y usa import_history_from_file_tool con el ID de la cuenta.
- SI ENVÍA VARIOS ARCHIVOS: Procesa cada uno, acumula cuántos movimientos llevas y pregunta a qué cuenta cargarlos cuando termine.
"""
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
            system_instruction = get_system_instruction(file_summary, current_mode, wisdom_context)

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
                phone = user_context.get("phone") or user_context.get("from_user")
                if phone:
                    async def send_feedback():
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"{BRIDGE_URL}/send-message",
                                json={"phone": phone, "message": "⏳ Procesando cambios en la Bóveda..."},
                                timeout=5,
                            )
                    import asyncio as _asyncio
                    _asyncio.create_task(send_feedback())
            except Exception as e:
                print(f"⚠️ No se pudo enviar feedback inmediato: {e}")

            try:
                tool_result = execute_function(tool_call.name, tool_call.args)
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
    """Se ejecuta cuando el usuario deja de enviar archivos por 4 segundos."""
    files = upload_buffers.pop(phone, [])
    if not files:
        print(f"ℹ️ Buffer vacío para {phone}, nada que procesar.")
        return

    target_phone = os.getenv("ADMIN_PHONE", phone)

    print(f"🚀 Procesando lote consolidado de {len(files)} archivos para {phone}...")
    await send_push_message(
        target_phone,
        f"⏳ Recibí {len(files)} archivos. Arranco el procesamiento; si ves este mensaje, sigo vivo.",
    )

    all_transactions = []
    processed_rows = 0
    for file in files:
        try:
            txs = await asyncio.to_thread(process_file_stream, file["path"], file["mime"])
            processed_rows += len(txs) if txs else 0
            if processed_rows and processed_rows % 300 == 0:
                await send_push_message(
                    target_phone,
                    f"⏳ Sigo analizando... llevo {processed_rows} movimientos extraídos.",
                )
            if txs:
                all_transactions.extend(txs)
        except Exception as e:
            print(f"⚠️ Error procesando {file.get('path')}: {e}")

    if not all_transactions:
        print("⚠️ No se extrajeron transacciones de los archivos.")
        await send_push_message(
            target_phone,
            "Recibí tus archivos pero no pude extraer movimientos. ¿Puedes reenviarlos en CSV/Excel estándar?",
        )
        debounce_generation.pop(phone, None)
        return

    previous_data = get_pending_data(phone) or []
    if not isinstance(previous_data, list):
        try:
            previous_data = list(previous_data)
        except Exception:
            previous_data = []

    final_data = previous_data + all_transactions
    save_pending_data(phone, final_data)

    total_monto = sum(t.get("amount", 0) for t in final_data)
    count = len(final_data)

    response_text = (
        f"📚 **Lote Procesado**\n"
        f"Recibí **{len(files)} archivos** y extraje **{count} movimientos** nuevos.\n\n"
        f"💰 **Total en Cola:** ${total_monto:,.0f}\n\n"
        f"**¿Qué hacemos con esto?**\n"
        f"1️⃣ Cargar a **Nubank**\n"
        f"2️⃣ Cargar a **Bancolombia**\n"
        f"3️⃣ Crear nueva cuenta\n\n"
        f"*Dime el nombre de la cuenta o envía más archivos.*"
    )

    print(f"📤 Enviando respuesta a ADMIN: {target_phone} (Ignorando {phone})")
    await send_push_message(target_phone, response_text)
    debounce_generation.pop(phone, None)


async def send_push_message(phone: str, text: str):
    """Cliente HTTP para hablar con el endpoint /send de Node."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{BRIDGE_URL}/send", json={"to": phone, "message": text})
    except Exception as e:
        print(f"❌ Error enviando Push a {phone}: {e!r}")


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
            filename = media_payload.get("filename") or media_payload.get("path")
            print(f"⏳ Buffering archivo: {filename}")

            upload_buffers.setdefault(user_phone, []).append({"path": media_payload.get("path"), "mime": mime_raw})
            gen = debounce_generation.get(user_phone, 0) + 1
            debounce_generation[user_phone] = gen
            threading.Thread(target=_debounce_worker, args=(user_phone, gen), daemon=True).start()
            print(f"⏲️ Timer armado para {user_phone} (gen={gen})")

            return {"status": "buffered", "message": None}

        # Otros media (audio/imagen) -> procesar normal
        wisdom_context = retrieve_wisdom(body, top_k=3)
        system_instruction = get_system_instruction(file_summary or "", current_mode or "NORMAL", wisdom_context)
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
            target_phone = os.getenv("ADMIN_PHONE", user_phone)
            print(f"📤 Enviando mensaje a {target_phone} (Ignorando {user_phone} si es LID)...")
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BRIDGE_URL}/send-message",
                    json={"phone": target_phone, "message": reply_text},
                    timeout=10,
                )
            print("✅ Mensaje entregado al puente.")
        except Exception as e:
            print(f"❌ Error enviando a WhatsApp: {e}")

    return {"status": "processed"}


@app.on_event("startup")
async def start_scheduler():
    try:
        scheduler.add_job(morning_briefing, CronTrigger(hour=7, minute=0))
        # Deshabilitado temporalmente para no bloquear el loop HTTP durante el sprint de buffer.
        # scheduler.add_job(check_emails, CronTrigger(minute="*/15"))
        scheduler.start()
        print("⏳ Scheduler iniciado: AFI ahora tiene vida propia.")
    except Exception as e:
        print(f"⚠️ Error iniciando scheduler: {e}")
