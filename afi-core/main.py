import os
import json
import datetime
from fastapi import FastAPI, Request
from pydantic import BaseModel
import google.generativeai as genai
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx
import email_ingest
import identity_manager
from tools import TOOLS_SCHEMA, get_financial_audit, create_category_tool, categorize_payees_tool
from database import init_db, get_user_context, save_user_context, get_conn
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
WHATSAPP_PUSH_URL = "http://afi-whatsapp:3000/send-message"
BRIDGE_URL = "http://afi-whatsapp:3000"

# Memoria de chat agéntico
chat_history = []
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
        email_ingest.process_emails()
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


def process_multimodal_request(user_text: str, media_path: str, media_mime: str, system_instruction: str) -> str:
    """Procesa audio/imagen con Gemini 2.5 Flash."""
    print(f"👁️ Procesando archivo: {media_path} ({media_mime})")
    try:
        uploaded_file = genai.upload_file(media_path, mime_type=media_mime)
        multimodal_prompt = f"""
CONTEXTO DEL USUARIO (Texto acompañante): "{user_text}"

TAREA:
Analiza este archivo (Audio o Imagen).
1. Si es AUDIO: Transcribe lo que dice y extrae la intención (Gasto, Consulta, Reflexión).
2. Si es IMAGEN: Extrae los datos financieros (Comercio, Total, Fecha).

ACCION:
Si detectas un gasto, actúa inmediatamente invocando las herramientas necesarias.
Si es una consulta, responde en Español.
"""
        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_instruction, tools=TOOLS_SCHEMA)
        response = model.generate_content([multimodal_prompt, uploaded_file])
        return response.text if response else "⚠️ No se obtuvo respuesta del modelo."
    except Exception as e:
        print(f"❌ Error multimodal: {e}")
        return "⚠️ No pude procesar el archivo. Intenta de nuevo."


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

        # 2. LOGICA DE MODO (SHERLOCK VS CFO)
        # Si es el Admin, no tiene resumen de archivos y su perfil está incompleto -> MODO SHERLOCK
        if user_profile and user_profile['role'] == 'admin' and not file_summary and user_profile['status'] == 'incomplete':
            system_instruction = """
Eres AFI, el Asesor Financiero Personal de Diego.

SITUACIÓN ACTUAL:
Estás en la fase de 'Discovery' (Investigación). No tienes datos históricos (CSVs) ni un perfil claro.

OBJETIVO:
Entrevistar a Diego para construir su 'Perfil Base' en 3 pasos rápidos.

REGLAS DE INTERACCIÓN:
1. NO pidas subir archivos todavía. Queremos conversar.
2. Haz una pregunta a la vez. Sé conciso.
3. Pregunta clave 1: "¿Cuáles son tus 3 gastos fijos más grandes?"
4. Pregunta clave 2: "¿Qué deuda te quita el sueño hoy?"
5. Pregunta clave 3: "¿Cuánto quieres ahorrar al mes?"

Cuando tengas las respuestas, confírmalas y di: "Perfil creado. Empecemos a registrar."
"""
        else:
            # MODO NORMAL (CFO) - Usa la memoria y herramientas existentes
            current_mode = "NORMAL"
            if state:
                current_mode = state.get("mode") or "NORMAL"

            # Autorecuperación de contexto (Si la DB está vacía pero hay archivo)
            if not file_summary:
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

        # 3. INVOCAR GEMINI
        model = genai.GenerativeModel(
            "gemini-2.5-flash",
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


@app.get("/")
def health_check():
    return {"status": "online", "system": "AFI Core"}


@app.post("/webhook/whatsapp")
async def receive_message(request: Request):
    data = await request.json()
    user_phone = data.get("from_user")
    body = data.get("body", "")
    print(f"📥 Brain recibió de {user_phone}: {body}")

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

    if data.get("hasMedia") and media_payload and media_payload.get("path"):
        wisdom_context = retrieve_wisdom(body, top_k=3)
        system_instruction = get_system_instruction(file_summary or "", current_mode or "NORMAL", wisdom_context)
        reply_text = process_multimodal_request(
            body,
            media_payload.get("path"),
            media_payload.get("mime") or "application/octet-stream",
            system_instruction,
        )
    else:
        # Flujo Texto Normal
        reply_text = ai_router(body, user)

    print(f"🧠 Gemini responde: {str(reply_text)[:80]}...")

    if reply_text:
        try:
            print(f"📤 Enviando mensaje a {user_phone}...")
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BRIDGE_URL}/send-message",
                    json={"phone": user_phone, "message": reply_text},
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
        scheduler.add_job(check_emails, CronTrigger(minute="*/15"))
        scheduler.start()
        print("⏳ Scheduler iniciado: AFI ahora tiene vida propia.")
    except Exception as e:
        print(f"⚠️ Error iniciando scheduler: {e}")
