import os
import datetime
from imap_tools import MailBox, AND
import google.generativeai as genai
import json
from db_ops import execute_insert, execute_query, ensure_account, insert_transactions
import tempfile

# Configuración
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
GENAI_KEY = os.getenv("GOOGLE_API_KEY")

if GENAI_KEY:
    genai.configure(api_key=GENAI_KEY)

def _get_user_id_by_email(email_address):
    # TODO: Implementar mapeo real email -> user_id si se agrega columna email a users
    # Por ahora, retornamos 1 (Admin)
    return 1

def _extract_data_with_gemini(text_content, file_path=None):
    """Usa Gemini para extraer transacciones de texto o archivo."""
    prompt = """
    Analiza este correo/archivo. Busca transacciones financieras (compras, transferencias, facturas).
    Devuelve un JSON con una lista de objetos:
    [
      {
        "date": "YYYY-MM-DD",
        "amount": -100.00, (negativo para gasto)
        "payee": "Nombre Comercio",
        "category": "Categoría sugerida",
        "account_hint": "Banco o Tarjeta mencionada"
      }
    ]
    Si no hay datos financieros, devuelve [].
    """
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    try:
        if file_path:
            file_upload = genai.upload_file(file_path)
            response = model.generate_content([prompt, file_upload])
        else:
            response = model.generate_content([prompt, text_content])
            
        json_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_text)
    except Exception as e:
        print(f"⚠️ Error Gemini parsing email: {e}")
        return []

def check_emails():
    if not EMAIL_USER or not EMAIL_PASS:
        print("⚠️ Credenciales de correo no configuradas.")
        return

    print("📧 Checking emails...")
    try:
        with MailBox(IMAP_SERVER).login(EMAIL_USER, EMAIL_PASS) as mailbox:
            # Buscar no leídos
            for msg in mailbox.fetch(AND(seen=False), limit=5):
                print(f"📨 Procesando correo: {msg.subject} de {msg.from_}")
                user_id = _get_user_id_by_email(msg.from_)
                
                transactions = []
                
                # 1. Analizar Adjuntos (Prioridad: PDF)
                pdf_processed = False
                for att in msg.attachments:
                    if att.filename.lower().endswith(".pdf"):
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                            tf.write(att.payload)
                            tf_path = tf.name
                        
                        print(f"   📎 Analizando PDF: {att.filename}")
                        txs = _extract_data_with_gemini("", file_path=tf_path)
                        if txs:
                            transactions.extend(txs)
                            pdf_processed = True
                        os.unlink(tf_path)

                # 2. Si no hubo PDFs útiles, analizar cuerpo
                if not pdf_processed and msg.text:
                     print("   📝 Analizando cuerpo del correo...")
                     txs = _extract_data_with_gemini(msg.text[:5000]) # Limitar caracteres
                     if txs:
                        transactions.extend(txs)

                # 3. Insertar en DB
                if transactions:
                    print(f"   💰 Encontradas {len(transactions)} transacciones.")
                    for tx in transactions:
                        # Asegurar cuenta
                        acc_name = tx.get("account_hint", "Email Import")
                        # OJO: ensure_account en db_ops no soporta user_id aun, pero insert_transactions sí debería.
                        # Necesitamos arreglar ensure_account para que use el contexto RLS o pasarle user_id si modificamos db_ops.
                        # Por simplicidad y tiempo, asumimos que ensure_account crea cuentas globales o para el admin (user_id=1 default en DB).
                        # Pero con RLS activado, ensure_account fallará si no inyectamos user_id en la conexión?
                        # get_conn() sin args usa user_id=None -> app.current_user_id null -> RLS block (si no es owner).
                        # PERO este script corre como proceso background, usa get_conn() -> conecta como afi_user (Owner).
                        # Al ser Owner, RLS se aplica SOLO si usamos FORCE RLS. Y LO USAMOS.
                        # Entonces necesitamos pasar user_id a las funciones de db_ops.
                        
                        # Fix temporal: inyectar manualmente transacciones usando execute_insert con user_id
                        
                        # 1. Resolver Account ID (manual query con RLS context)
                        # ensure_account en db_ops no recibe user_id. 
                        # Vamos a usar execute_query para buscarla.
                        
                        existing_acc = execute_query(
                            "SELECT account_id FROM accounts WHERE account_name = %s", 
                            (acc_name,),
                            fetch_one=True, 
                            user_id=user_id
                        )
                        
                        if existing_acc:
                            acc_id = existing_acc[0]
                        else:
                            # Crear cuenta
                            execute_insert(
                                "INSERT INTO accounts (account_name, account_type_id, currency_code, user_id) VALUES (%s, 1, 'COP', %s)",
                                (acc_name, user_id),
                                user_id=user_id
                            )
                            acc_id_row = execute_query("SELECT account_id FROM accounts WHERE account_name = %s", (acc_name,), fetch_one=True, user_id=user_id)
                            acc_id = acc_id_row[0] if acc_id_row else None
                        
                        if acc_id:
                            execute_insert(
                                """
                                INSERT INTO transactions (account_id, date, amount, description, category, user_id, import_source)
                                VALUES (%s, %s, %s, %s, %s, %s, 'email_agent')
                                """,
                                (acc_id, tx.get('date'), tx.get('amount'), tx.get('payee'), tx.get('category'), user_id),
                                user_id=user_id
                            )
                    
                    print("   ✅ Transacciones guardadas.")
                else:
                    print("   ⚠️ No se detectaron datos financieros.")

                # Marcar como visto es automático con MailBox context? No, hay que setearlo.
                # imap_tools por defecto NO marca seen si usamos fetch(mark_seen=True).
                # Pero en el loop `mailbox.fetch(AND(seen=False))` no marca.
                # Podemos usar mailbox.flag(msg.uid, imap_tools.MailMessageFlags.SEEN, True)
                # Pero fetch tiene arg mark_seen=True.
                
                # Para el script actual:
                mailbox.flag(msg.uid, '\Seen', True)

    except Exception as e:
        print(f"❌ Error en Email Agent: {e}")

if __name__ == "__main__":
    check_emails()