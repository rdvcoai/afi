#!/usr/bin/env python3
"""
Auditoría COMPLETA de correos - Lee TODOS los correos del último año
Extrae: cuentas bancarias, pasivos, activos, suscripciones
"""
import os
import json
import datetime
from typing import Dict, Any, List
from imap_tools import MailBox, AND
import httpx

# Config
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama-local:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
DAYS_BACK = int(os.getenv("AUDIT_DAYS", "365"))

# Resultados
results = {
    "cuentas_bancarias": [],
    "pasivos": [],
    "activos": [],
    "suscripciones": [],
    "transacciones": [],
    "total_correos": 0,
    "procesados": 0
}

def analyze_with_llm(subject: str, body: str, from_email: str) -> Dict[str, Any]:
    """Usa LLM para extraer información financiera"""
    prompt = f"""Analiza este correo y extrae TODA la información financiera en JSON.

Formato esperado:
{{
  "tipo": "banco|suscripcion|factura|inversión|prestamo|tarjeta",
  "cuentas": ["Banco X cuenta ****1234", ...],
  "pasivos": [{{"tipo": "préstamo|tarjeta|deuda", "monto": 1000, "entidad": "Banco"}}, ...],
  "activos": [{{"tipo": "inversión|cuenta|propiedad", "monto": 5000, "entidad": "Broker"}}, ...],
  "suscripciones": [{{"servicio": "Netflix", "monto_mensual": 15.99}}, ...],
  "transaccion": {{"fecha": "YYYY-MM-DD", "monto": -500, "concepto": "Pago"}},
  "es_financiero": true
}}

Si NO es financiero: {{"es_financiero": false}}

De: {from_email}
Asunto: {subject}
Cuerpo: {body[:4000]}
"""

    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_ctx": 8192}
                }
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")

            # Extraer JSON
            if "{" in raw and "}" in raw:
                start = raw.find("{")
                end = raw.rfind("}") + 1
                return json.loads(raw[start:end])
    except Exception as e:
        print(f"⚠️ Error LLM: {e}")

    return {"es_financiero": false}

def save_results():
    """Guardar resultados a archivo"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"/data/auditoria_{timestamp}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n📊 Resultados guardados en: {output_file}")

def main():
    if not EMAIL_USER or not EMAIL_PASS:
        print("❌ Sin credenciales de email")
        return

    since_date = datetime.date.today() - datetime.timedelta(days=DAYS_BACK)
    print(f"🔍 Iniciando auditoría COMPLETA desde {since_date}")
    print(f"📧 Usuario: {EMAIL_USER}")
    print(f"🤖 Modelo: {MODEL}\n")

    # Warmup
    print("🔥 Calentando motor IA...")
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": MODEL, "prompt": "test", "stream": False},
            timeout=300.0
        )
        print("✅ Motor listo\n")
    except Exception as e:
        print(f"⚠️ Warmup falló: {e}\n")

    try:
        with MailBox(IMAP_SERVER).login(EMAIL_USER, EMAIL_PASS) as mailbox:
            # Procesar TODOS los correos del período
            emails = list(mailbox.fetch(AND(date_gte=since_date)))
            results["total_correos"] = len(emails)

            print(f"📬 Encontrados {len(emails)} correos. Procesando...\n")

            for idx, msg in enumerate(emails, 1):
                print(f"[{idx}/{len(emails)}] {msg.subject[:50]}...")

                body = msg.text or msg.html or ""
                analysis = analyze_with_llm(msg.subject, body, msg.from_)

                if not analysis.get("es_financiero"):
                    continue

                results["procesados"] += 1

                # Agregar hallazgos
                if analysis.get("cuentas"):
                    results["cuentas_bancarias"].extend(analysis["cuentas"])

                if analysis.get("pasivos"):
                    results["pasivos"].extend(analysis["pasivos"])

                if analysis.get("activos"):
                    results["activos"].extend(analysis["activos"])

                if analysis.get("suscripciones"):
                    results["suscripciones"].extend(analysis["suscripciones"])

                if analysis.get("transaccion"):
                    results["transacciones"].append({
                        **analysis["transaccion"],
                        "from": msg.from_,
                        "subject": msg.subject
                    })

                # Guardar progreso cada 10 correos
                if idx % 10 == 0:
                    save_results()

    except Exception as e:
        print(f"❌ Error: {e}")

    finally:
        save_results()
        print(f"\n✅ Auditoría completa:")
        print(f"   📧 Total correos: {results['total_correos']}")
        print(f"   💼 Procesados: {results['procesados']}")
        print(f"   🏦 Cuentas: {len(results['cuentas_bancarias'])}")
        print(f"   💳 Pasivos: {len(results['pasivos'])}")
        print(f"   💰 Activos: {len(results['activos'])}")
        print(f"   🔄 Suscripciones: {len(results['suscripciones'])}")
        print(f"   📊 Transacciones: {len(results['transacciones'])}")

if __name__ == "__main__":
    main()
