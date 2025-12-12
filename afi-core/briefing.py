import os
import datetime
import google.generativeai as genai
from database import get_conn

def get_financial_summary():
    """Obtiene resumen financiero de la DB."""
    summary = {
        "balance": 0.0,
        "yesterday_spent": 0.0,
        "month_spent": 0.0
    }
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # 1. Saldo Total (Net Worth aproximado: suma de todas las transacciones)
                cur.execute("SELECT SUM(amount) FROM transactions;")
                row = cur.fetchone()
                if row and row[0] is not None:
                    summary["balance"] = float(row[0])

                # 2. Gastos de Ayer (Solo montos negativos)
                cur.execute("""
                    SELECT SUM(amount) FROM transactions 
                    WHERE date = CURRENT_DATE - INTERVAL '1 day' 
                    AND amount < 0;
                """)
                row = cur.fetchone()
                if row and row[0] is not None:
                    summary["yesterday_spent"] = abs(float(row[0])) # Mostrar positivo como "gasto"

                # 3. Gastos del Mes (Solo montos negativos)
                cur.execute("""
                    SELECT SUM(amount) FROM transactions 
                    WHERE date >= date_trunc('month', CURRENT_DATE) 
                    AND amount < 0;
                """)
                row = cur.fetchone()
                if row and row[0] is not None:
                    summary["month_spent"] = abs(float(row[0]))

    except Exception as e:
        print(f"⚠️ Error obteniendo resumen financiero: {e}")
        # Retornamos ceros o lo que se haya podido calcular

    return summary

def generate_briefing_text():
    """Genera el texto del briefing usando Gemini."""
    stats = get_financial_summary()
    
    # Formateo de moneda
    bal = f"${stats['balance']:,.0f}"
    yest = f"${stats['yesterday_spent']:,.0f}"
    month = f"${stats['month_spent']:,.0f}"
    
    today = datetime.date.today().strftime('%A %d de %B')
    
    prompt = f"""
Eres AFI, mi CFO personal. Hoy es {today}.

DATOS FINANCIEROS ACTUALES:
- Patrimonio Neto (Saldo Total): {bal}
- Gastos de Ayer: {yest}
- Gastos Acumulados del Mes: {month}

INSTRUCCIÓN:
Actúa como un CFO proactivo y motivador (estilo Mr. Money Mustache / Ramit Sethi).
Escribe un mensaje de buenos días para WhatsApp.
1. Saluda brevemente.
2. Presenta los números clave de forma digerible.
3. Si los gastos de ayer fueron altos (>{yest}), haz una advertencia amable. Si fueron bajos, felicita.
4. Cierra con una frase corta de impacto sobre riqueza o disciplina.

FORMATO:
Usa emojis.
Máximo 3 párrafos cortos.
No uses markdown complejo (negritas **texto** están bien).
"""

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Error generando briefing: {e}"
