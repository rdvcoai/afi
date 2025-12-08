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
from database import init_db, get_user_context, save_user_context

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
        model = genai.GenerativeModel("gemini-2.5-pro")
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


def ai_router(text: str, user_context: dict) -> str:
    """Bucle agéntico con Gemini y function-calling."""
    global chat_history
    print(f"🧠 [DEBUG] Enviando a Gemini: {text}")
    try:
        phone = user_context.get("phone") or user_context.get("from_user")

        # Recuperar contexto persistente
        state = get_user_context(phone)
        file_summary = ""
        has_data = False
        if state and state.get("file_context"):
            file_summary = state["file_context"]
            has_data = True
        else:
            # Intentar auditar disco si DB vacía
            print("🔍 DB vacía para usuario. Leyendo CSV físico...")
            try:
                raw_audit = get_financial_audit()
                if raw_audit:
                    file_summary = raw_audit
                    has_data = True
                    save_user_context(phone, file_summary=raw_audit, mode="ONBOARDING")
            except Exception as e:
                print(f"⚠️ No hay CSV o error lectura: {e}")

        system_instruction = f"""
Eres AFI, el CFO Personal y Asesor Patrimonial de Diego.
No eres un bot. Eres un experto financiero de alto nivel.

MEMORIA PERSISTENTE (datos del usuario):
{file_summary[:5000]}

MODOS DE OPERACIÓN:
1. MODO AUDITOR (si hay datos): Usa get_financial_audit. Si hay transacciones, analízalas, agrupa patrones y propone categorías. Usa create_category_tool y categorize_payees_tool con confirmación.
2. MODO ENTREVISTADOR (si NO hay datos o has_data=False): Haz preguntas socráticas sobre gastos fijos, deudas, métodos de pago; pide foto/nota de voz si falta info. No te quedes callado.

REGLAS:
1. Habla como humano experto, directo y estratégico; usa emojis con moderación.
2. Usa herramientas para ver datos y ejecutar cambios; espera resultados reales, no inventes errores.
3. Si el usuario pide separar/crear categorías, usa create_category_tool/categorize_payees_tool y confirma.
4. Si no hay datos, entrevista proactiva: “No veo historial, cuéntame tus 3 gastos fijos más grandes”.
"""

        model = genai.GenerativeModel(
            "gemini-2.5-pro",
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
