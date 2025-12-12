import os
import datetime
import google.generativeai as genai
from database import get_conn

ADMIN_PHONE = os.getenv("ADMIN_PHONE")
GENAI_KEY = os.getenv("GOOGLE_API_KEY")
if GENAI_KEY:
    genai.configure(api_key=GENAI_KEY)


def _fetch_snapshot():
    """Obtiene métricas básicas para el briefing."""
    snapshot = {
        "liquidity": None,
        "yesterday_spend": None,
        "month_spend": None,
    }
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions;")
                    row = cur.fetchone()
                    snapshot["liquidity"] = float(row[0]) if row and row[0] is not None else None
                except Exception as e:
                    print(f"⚠️ Error obteniendo liquidez aproximada: {e}")
                    conn.rollback()

                try:
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(amount), 0)
                        FROM transactions
                        WHERE date >= CURRENT_DATE - INTERVAL '1 day'
                        AND amount < 0;
                        """
                    )
                    row = cur.fetchone()
                    snapshot["yesterday_spend"] = abs(float(row[0])) if row and row[0] is not None else None
                except Exception as e:
                    print(f"⚠️ Error obteniendo gastos de ayer: {e}")

                try:
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(amount), 0)
                        FROM transactions
                        WHERE date >= date_trunc('month', CURRENT_DATE)
                        AND amount < 0;
                        """
                    )
                    row = cur.fetchone()
                    snapshot["month_spend"] = abs(float(row[0])) if row and row[0] is not None else None
                except Exception as e:
                    print(f"⚠️ Error obteniendo gastos del mes: {e}")
    except Exception as e:
        print(f"⚠️ No se pudo conectar a la DB para briefing: {e}")

    return snapshot


def _fmt(val):
    if val is None:
        return "N/D"
    try:
        return f"${val:,.0f}"
    except Exception:
        return str(val)


async def send_morning_briefing():
    """Genera y envía el briefing de las 7 AM."""
    print("🌅 Ejecutando Morning Briefing...")
    snapshot = _fetch_snapshot()

    prompt = f"""
ACTÚA COMO: CFO Personal Proactivo.
CONTEXTO: Son las 7:00 AM.
DATOS:
- Liquidez disponible: {_fmt(snapshot.get('liquidity'))}
- Gastos de ayer: {_fmt(snapshot.get('yesterday_spend'))}
- Gasto acumulado del mes: {_fmt(snapshot.get('month_spend'))}

TAREA: Escribe un mensaje de WhatsApp corto, motivador y directo.
- Si gastó mucho ayer, da un toque de atención suave (austeridad).
- Si no gastó, felicítalo.
- Cierra con el foco del día.

SALIDA: Solo el texto del mensaje.
"""

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        message = (response.text or "").strip()
    except Exception as e:
        print(f"⚠️ Error generando briefing con Gemini: {e}")
        message = "⚠️ No pude generar el briefing de esta mañana."

    if not ADMIN_PHONE:
        print("⚠️ No hay ADMIN_PHONE configurado para el briefing.")
        return

    try:
        from message_queue import enqueue_message

        await enqueue_message(ADMIN_PHONE, message)
        print("✅ Briefing enviado.")
    except Exception as e:
        print(f"⚠️ Error enviando briefing: {e}")
