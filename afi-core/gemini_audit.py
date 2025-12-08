#!/usr/bin/env python3
"""
Auditoría COMPLETA con Gemini 2.5 Flash
Lee TODOS los correos del último año y extrae información financiera
"""
import os
import json
import datetime
from typing import Dict, Any
from imap_tools import MailBox, AND
import google.generativeai as genai

# Configuración
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DAYS_BACK = int(os.getenv("AUDIT_DAYS", "365"))

# Modelo Gemini 2.5 Flash (más eficiente y económico)
MODEL_NAME = "gemini-2.5-flash"

# Resultados
results = {
    "cuentas_bancarias": set(),  # Usar set para evitar duplicados
    "pasivos": [],
    "activos": [],
    "suscripciones": [],
    "transacciones": [],
    "entidades_financieras": set(),
    "total_correos": 0,
    "procesados": 0,
    "financieros": 0
}

def analyze_with_gemini(subject: str, body: str, from_email: str, date: str) -> Dict[str, Any]:
    """Usa Gemini 2.5 Flash para extraer información financiera"""

    prompt = f"""Analiza este correo y extrae TODA la información financiera relevante.

INSTRUCCIONES:
1. Identifica si es un correo financiero (banco, tarjeta, inversión, factura, suscripción, préstamo)
2. Extrae TODAS las cuentas bancarias mencionadas (número parcial tipo ****1234)
3. Identifica pasivos (deudas, préstamos, saldos de tarjetas, cuotas pendientes)
4. Identifica activos (inversiones, ahorros, propiedades, cuentas)
5. Detecta suscripciones y servicios recurrentes
6. Extrae transacciones con fecha y monto

FORMATO DE RESPUESTA (JSON estricto):
{{
  "es_financiero": true/false,
  "tipo": "banco|tarjeta|inversion|factura|suscripcion|prestamo|otro",
  "entidad": "Nombre del banco/empresa",
  "cuentas": ["Cuenta ****1234", "Tarjeta ****5678"],
  "pasivos": [
    {{"tipo": "tarjeta_credito|prestamo|deuda", "monto": 1000000, "descripcion": "Saldo tarjeta", "entidad": "Banco X"}}
  ],
  "activos": [
    {{"tipo": "ahorro|inversion|cuenta", "monto": 5000000, "descripcion": "Cuenta ahorros", "entidad": "Banco Y"}}
  ],
  "suscripciones": [
    {{"servicio": "Netflix", "monto_mensual": 45000, "moneda": "COP"}}
  ],
  "transaccion": {{
    "fecha": "{date}",
    "monto": -50000,
    "concepto": "Pago servicios",
    "categoria": "servicios"
  }}
}}

Si NO es financiero, responde: {{"es_financiero": false}}

CORREO A ANALIZAR:
De: {from_email}
Fecha: {date}
Asunto: {subject}
Cuerpo:
{body[:6000]}

Responde SOLO con el JSON, sin explicaciones adicionales.
"""

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Extraer JSON de la respuesta
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        # Limpiar y parsear
        if "{" in raw and "}" in raw:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            return data

    except Exception as e:
        print(f"⚠️ Error Gemini: {e}")

    return {"es_financiero": False}


def save_results():
    """Guardar resultados a archivo JSON"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"/data/auditoria_gemini_{timestamp}.json"

    # Convertir sets a listas para JSON
    output_data = {
        **results,
        "cuentas_bancarias": sorted(list(results["cuentas_bancarias"])),
        "entidades_financieras": sorted(list(results["entidades_financieras"]))
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Guardado en: {output_file}")
    return output_file


def print_summary():
    """Imprimir resumen de la auditoría"""
    print("\n" + "="*60)
    print("📊 RESUMEN DE AUDITORÍA FINANCIERA")
    print("="*60)
    print(f"📧 Total correos analizados: {results['total_correos']}")
    print(f"💼 Correos financieros: {results['financieros']}")
    print(f"🏦 Cuentas bancarias únicas: {len(results['cuentas_bancarias'])}")
    print(f"🏢 Entidades financieras: {len(results['entidades_financieras'])}")
    print(f"💳 Pasivos detectados: {len(results['pasivos'])}")
    print(f"💰 Activos detectados: {len(results['activos'])}")
    print(f"🔄 Suscripciones: {len(results['suscripciones'])}")
    print(f"📊 Transacciones: {len(results['transacciones'])}")
    print("="*60)


def main():
    if not EMAIL_USER or not EMAIL_PASS:
        print("❌ Sin credenciales de email")
        return

    if not GOOGLE_API_KEY:
        print("❌ Sin API key de Google")
        return

    # Configurar Gemini
    genai.configure(api_key=GOOGLE_API_KEY)

    since_date = datetime.date.today() - datetime.timedelta(days=DAYS_BACK)

    print("="*60)
    print("🚀 AUDITORÍA FINANCIERA COMPLETA")
    print("="*60)
    print(f"📧 Email: {EMAIL_USER}")
    print(f"📅 Desde: {since_date}")
    print(f"🤖 Modelo: {MODEL_NAME}")
    print("="*60 + "\n")

    try:
        with MailBox(IMAP_SERVER).login(EMAIL_USER, EMAIL_PASS) as mailbox:
            # Obtener TODOS los correos del período
            emails = list(mailbox.fetch(AND(date_gte=since_date)))
            results["total_correos"] = len(emails)

            print(f"📬 Encontrados {len(emails)} correos\n")
            print("Procesando...\n")

            for idx, msg in enumerate(emails, 1):
                subject = msg.subject or "(Sin asunto)"
                print(f"[{idx}/{len(emails)}] {subject[:60]}...")

                body = msg.text or msg.html or ""
                date_str = msg.date.strftime("%Y-%m-%d") if msg.date else ""

                analysis = analyze_with_gemini(
                    subject=subject,
                    body=body,
                    from_email=msg.from_ or "",
                    date=date_str
                )

                results["procesados"] += 1

                if not analysis.get("es_financiero"):
                    continue

                results["financieros"] += 1

                # Extraer información
                if analysis.get("entidad"):
                    results["entidades_financieras"].add(analysis["entidad"])

                if analysis.get("cuentas"):
                    for cuenta in analysis["cuentas"]:
                        results["cuentas_bancarias"].add(cuenta)

                if analysis.get("pasivos"):
                    results["pasivos"].extend(analysis["pasivos"])

                if analysis.get("activos"):
                    results["activos"].extend(analysis["activos"])

                if analysis.get("suscripciones"):
                    results["suscripciones"].extend(analysis["suscripciones"])

                if analysis.get("transaccion"):
                    tx = {
                        **analysis["transaccion"],
                        "from": msg.from_,
                        "subject": subject,
                        "tipo": analysis.get("tipo"),
                        "entidad": analysis.get("entidad")
                    }
                    results["transacciones"].append(tx)

                # Guardar progreso cada 25 correos
                if idx % 25 == 0:
                    save_results()
                    print_summary()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        output_file = save_results()
        print_summary()

        print(f"\n✅ Auditoría completada")
        print(f"📄 Resultados: {output_file}\n")


if __name__ == "__main__":
    main()
