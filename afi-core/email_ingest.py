import os
from imap_tools import MailBox, AND
import google.generativeai as genai

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")  # App Password de Google

def process_emails():
    if not EMAIL_USER or not EMAIL_PASS:
        print("⚠️ No hay credenciales de email configuradas.")
        return

    print("📧 Conectando a IMAP...")
    try:
        with MailBox(IMAP_SERVER).login(EMAIL_USER, EMAIL_PASS) as mailbox:
            for msg in mailbox.fetch(AND(seen=False)):
                print(f"📩 Procesando email de {msg.from_}: {msg.subject}")
                prompt = f"""
Analiza este correo bancario. Si es una transacción, extrae JSON:
{{ "amount": 1000, "payee": "Comercio", "date": "YYYY-MM-DD", "is_transaction": true }}
Si no es transacción, devuelve {{ "is_transaction": false }}.

Cuerpo: {msg.text or msg.html}
"""
                try:
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    _ = model.generate_content(prompt)
                except Exception as e:
                    print(f"⚠️ Error llamando a Gemini: {e}")
                # Marcar como leído podría hacerse aquí
    except Exception as e:
        print(f"❌ Error IMAP: {e}")
