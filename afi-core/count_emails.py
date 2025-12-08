#!/usr/bin/env python3
"""Cuenta correos del último año"""
import os
import datetime
from imap_tools import MailBox, AND

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
DAYS_BACK = int(os.getenv("AUDIT_DAYS", "365"))

if not EMAIL_USER or not EMAIL_PASS:
    print("❌ Sin credenciales")
    exit(1)

since_date = datetime.date.today() - datetime.timedelta(days=DAYS_BACK)

print(f"📧 Conectando a {EMAIL_USER}...")
print(f"📅 Contando correos desde {since_date}\n")

try:
    with MailBox(IMAP_SERVER).login(EMAIL_USER, EMAIL_PASS) as mailbox:
        emails = list(mailbox.fetch(AND(date_gte=since_date)))
        total = len(emails)

        print("="*60)
        print(f"📊 TOTAL CORREOS: {total:,}")
        print("="*60)

        # Estimación de tiempo
        tiempo_por_correo = 3  # segundos promedio con Gemini Flash
        tiempo_total_seg = total * tiempo_por_correo

        horas = tiempo_total_seg // 3600
        minutos = (tiempo_total_seg % 3600) // 60

        print(f"\n⏱️  ESTIMACIÓN DE TIEMPO:")
        print(f"   • Por correo: ~{tiempo_por_correo} segundos")
        print(f"   • Tiempo total: {horas}h {minutos}m")
        print(f"   • Finalización aprox: ", end="")

        ahora = datetime.datetime.now()
        fin = ahora + datetime.timedelta(seconds=tiempo_total_seg)
        print(fin.strftime("%H:%M"))

        print("\n" + "="*60)

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
