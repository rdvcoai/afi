import os
import json
import datetime
import time
from typing import Optional, Dict, Any, List

import httpx
from imap_tools import MailBox, AND

# Configuración
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_FOLDER = os.getenv("EMAIL_FOLDER", "INBOX")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama-local:11434")
MODEL_LOCAL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180.0"))  # hasta 3 min para CPU inference

NODE_BASE = os.getenv("NODE_BRIDGE_URL", "http://afi-whatsapp:3000")


def call_local_llm(body: str) -> Optional[Dict[str, Any]]:
    """
    Usa Qwen local para extraer {date, amount, payee} de un correo.
    """
    body = (body or "")[:3500]  # recortar para no saturar el modelo
    prompt = f"""
Eres un extractor financiero. Lee el texto y devuelve SOLO un JSON.
Formato: {{"date": "YYYY-MM-DD", "amount": 12345.67, "payee": "Nombre", "is_transaction": true}}
Si no hay transacción, responde {{"is_transaction": false}}.
Texto:
{body}
    """
    try:
        # Timeout extendido para CPU inference
        with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
            resp = client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL_LOCAL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_ctx": 2048, "temperature": 0.1},
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
    except Exception as e:
        print(f"❌ Error llamando a Ollama: {e}")
        return None

    raw = raw.strip()
    if "{" in raw and "}" in raw:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        raw = raw[start:end]
    try:
        data = json.loads(raw)
        return data
    except Exception as e:
        print(f"⚠️ No pude parsear JSON de Qwen: {e} -> {raw}")
        return None


def search_transactions(date_obj: datetime.date, amount: float) -> List[Dict[str, Any]]:
    payload = {
        "min_date": (date_obj - datetime.timedelta(days=1)).isoformat(),
        "max_date": (date_obj + datetime.timedelta(days=1)).isoformat(),
        "min_amount": amount,
        "max_amount": amount,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(f"{NODE_BASE}/transactions/search", json=payload)
            r.raise_for_status()
            return r.json() or []
    except Exception as e:
        print(f"⚠️ Error consultando transacciones: {e}")
        return []


def update_transaction(tx_id: str, notes: str):
    try:
        with httpx.Client(timeout=20.0) as client:
            client.post(
                f"{NODE_BASE}/transaction/update",
                json={"id": tx_id, "updates": {"cleared": True, "notes": notes}},
            )
    except Exception as e:
        print(f"⚠️ Error actualizando transacción: {e}")


def add_transaction(tx: Dict[str, Any]):
    try:
        with httpx.Client(timeout=20.0) as client:
            client.post(
                f"{NODE_BASE}/transaction/add",
                json={
                    "date": tx["date"],
                    "amount": tx["amount"],
                    "payee": tx["payee"],
                    "notes": tx.get("notes", ""),
                },
            )
    except Exception as e:
        print(f"⚠️ Error creando transacción: {e}")


def reconcile(tx: Dict[str, Any], dry_run: bool = True):
    signed_amount = -abs(tx["amount"])
    tx["amount"] = signed_amount
    candidates = search_transactions(tx["date"], signed_amount)
    if candidates:
        target = candidates[0]
        print(f"🔗 Conciliando email '{tx['payee']}' con '{target.get('imported_payee') or target.get('payee_name')}'")
        if not dry_run:
            current_notes = target.get("notes") or ""
            new_notes = f"{current_notes} [Ref: Email]"
            update_transaction(target.get("id"), new_notes)
    else:
        print(f"✨ Nuevo histórico: {signed_amount} en {tx['payee']} ({tx['date']})")
        if not dry_run:
            add_transaction(tx)


def process_mailbox(days_back: int = 7, dry_run: bool = True):
    if not EMAIL_USER or not EMAIL_PASS:
        print("⚠️ Sin credenciales de email, abortando auditoría.")
        return

    since_date = datetime.date.today() - datetime.timedelta(days=days_back)
    print(f"🔎 Auditoría: leyendo correos desde {since_date} (dry_run={dry_run})")
    try:
        with MailBox(IMAP_SERVER).login(EMAIL_USER, EMAIL_PASS) as mailbox:
            mailbox.folder.set(EMAIL_FOLDER)
            for msg in mailbox.fetch(AND(date_gte=since_date)):
                body = msg.text or msg.html or ""
                tx = call_local_llm(body)
                if not tx or not tx.get("is_transaction"):
                    continue
                try:
                    tx_date = datetime.datetime.strptime(tx["date"], "%Y-%m-%d").date()
                except Exception:
                    print(f"⚠️ Fecha inválida en email: {tx}")
                    continue
                tx_payload = {
                    "date": tx_date.isoformat(),
                    "amount": float(tx.get("amount", 0)),
                    "payee": tx.get("payee") or (msg.from_ or "Desconocido"),
                    "notes": f"{msg.subject or ''}".strip(),
                }
                reconcile(tx_payload, dry_run=dry_run)
    except Exception as e:
        print(f"❌ Error en auditoría histórica: {e}")

def warmup_model():
    """
    Carga el modelo en RAM antes de procesar correos.
    """
    print("🔥 Calentando motor de IA Local (puede tardar ~60s en CPU)...")
    try:
        httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": MODEL_LOCAL, "prompt": "hi", "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        print("✅ Motor listo y caliente.")
    except Exception as e:
        print(f"⚠️ Warmup falló, continuamos: {e}")

if __name__ == "__main__":
    days = int(os.getenv("AUDIT_DAYS", "7"))
    # Solo es False si explícitamente se pasa "false"
    dry = os.getenv("AUDIT_DRY_RUN", "true").lower() != "false"
    warmup_model()
    process_mailbox(days_back=days, dry_run=dry)
