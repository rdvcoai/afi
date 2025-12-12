import os
import pandas as pd
import psycopg2
import re
from datetime import datetime, timedelta
import glob
import hashlib
import httpx
import google.generativeai as genai

# Configuración DB
DB_HOST = "afi_db"
DB_NAME = os.getenv("POSTGRES_DB", "afi_brain")
DB_USER = os.getenv("POSTGRES_USER", "afi_user")
DB_PASS = os.getenv("DB_PASS") or os.getenv("POSTGRES_PASSWORD")

CSV_DIR = "/app/data/csv/CSV" # Ruta dentro del contenedor

# Configuración Alertas
ALERT_THRESHOLD = 200000
GENAI_KEY = os.getenv("GOOGLE_API_KEY")
if GENAI_KEY:
    genai.configure(api_key=GENAI_KEY)

WHATSAPP_PUSH_URL = os.getenv("WHATSAPP_PUSH_URL", "http://afi-whatsapp:3000/send-message")
ADMIN_PHONE = os.getenv("ADMIN_PHONE")

# Diccionario de meses español a número
MESES_ES = {
    'Ene': '01', 'Feb': '02', 'Mar': '03', 'Abr': '04', 'May': '05', 'Jun': '06',
    'Jul': '07', 'Ago': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dic': '12',
    'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04', 'may': '05', 'jun': '06',
    'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dic': '12'
}

def get_db_connection():
    try:
        return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    except Exception as e:
        print(f"❌ Error DB: {e}")
        return None

def parse_date_spanish(date_str):
    # Formatos tipo: 04Dic2024, 13Ago2025
    for mes, num in MESES_ES.items():
        if mes in date_str:
            date_str = date_str.replace(mes, num)
            break
    try:
        # Intentar formato DDMMYYYY (ej: 04122024 derivado de 04Dic2024)
        return datetime.strptime(date_str, "%d%m%Y").date()
    except ValueError:
        pass
    return None

def parse_flexible_date(date_obj):
    if pd.isna(date_obj): return None
    date_str = str(date_obj).strip()
    
    # 1. ISO YYYY-MM-DD
    try: return datetime.strptime(date_str, "%Y-%m-%d").date()
    except: pass
    
    # 2. DD/MM/YYYY
    try: return datetime.strptime(date_str, "%d/%m/%Y").date()
    except: pass
    
    # 3. Español (04Dic2024)
    res = parse_date_spanish(date_str)
    if res: return res
    
    # 4. DD/MM (Asumir año actual o pasado reciente)
    try: 
        dt = datetime.strptime(date_str, "%d/%m")
        return dt.replace(year=datetime.now().year).date()
    except: pass

    return None

def clean_amount(val):
    if pd.isna(val): return 0.0
    s = str(val).replace('$', '').replace(',', '').replace(' ', '')
    try:
        return float(s)
    except:
        return 0.0

def check_and_alert_transaction(amount, description, account_name, date_obj):
    """
    Analiza si el gasto es inusual y envía alerta.
    Regla: Gasto > Umbral Y Fecha reciente (< 3 días).
    """
    try:
        # 1. Validar condiciones básicas
        if abs(amount) < ALERT_THRESHOLD:
            return
        
        # Verificar recencia (solo alertar sobre lo nuevo)
        days_diff = (datetime.now().date() - date_obj).days
        if days_diff > 3:
            return

        print(f"🚨 Analizando posible alerta: {description} (${amount})")

        # 2. Consultar a Gemini
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
        El usuario gastó ${amount:,.0f} en '{description}' (Cuenta: {account_name}).
        
        TAREA:
        ¿Es esto un gasto potencialmente riesgoso, inusual o que requiera atención inmediata?
        (Ej: Compras grandes, suscripciones desconocidas, fraudes comunes).
        
        SI lo es: Escribe un mensaje de ALERTA corto y amable para WhatsApp (Max 2 frases). Pregunta si reconoce el cargo.
        NO lo es: Responde "OK".
        """
        response = model.generate_content(prompt)
        text = response.text.strip()

        if "OK" in text and len(text) < 10:
            return

        # 3. Enviar Alerta
        if ADMIN_PHONE:
            with httpx.Client(timeout=10) as client:
                client.post(WHATSAPP_PUSH_URL, json={"phone": ADMIN_PHONE, "message": f"⚠️ **Alerta de Gasto**\n\n{text}"})
                print("✅ Alerta enviada.")

    except Exception as e:
        print(f"⚠️ Error en sistema de alertas: {e}")

def process_file(file_path):
    filename = os.path.basename(file_path)
    print(f"\n📂 Procesando: {filename}")
    
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"   ❌ Error leyendo CSV: {e}")
        return

    # Normalización de Columnas
    df.columns = [c.lower().strip() for c in df.columns]
    
    records = []
    
    # ESTRATEGIA 1: Archivos "Final Simple" (cuenta2029, rappicard)
    if 'fecha' in df.columns and ('valor' in df.columns) and ('cuenta' in df.columns or 'concepto' in df.columns):
        print("   -> Detectado formato: Estructurado Simple")
        for _, row in df.iterrows():
            f = parse_flexible_date(row.get('fecha'))
            desc = row.get('descripcion') or row.get('concepto') or "Sin descripción"
            val = clean_amount(row.get('valor'))
            acc = str(row.get('cuenta', filename.split('.')[0])) # Usar nombre archivo si no hay col cuenta
            
            if f:
                records.append((f, desc, val, acc))

    # ESTRATEGIA 2: Crediexpress / Español
    elif 'operacion' in df.columns and 'clase' in df.columns:
        print("   -> Detectado formato: Crediexpress")
        for _, row in df.iterrows():
            f = parse_flexible_date(row.get('fecha'))
            desc = f"{row.get('clase')} - {row.get('operacion')}"
            val = clean_amount(row.get('valor'))
            acc = "Crediexpress"
            if f: records.append((f, desc, val, acc))
            
    # ESTRATEGIA 3: Nequi
    elif 'saldo' in df.columns and 'periodo' in df.columns:
         print("   -> Detectado formato: Nequi")
         for _, row in df.iterrows():
            f = parse_flexible_date(row.get('fecha'))
            desc = row.get('descripcion', 'Movimiento Nequi')
            val = clean_amount(row.get('valor'))
            acc = "Nequi"
            if f: records.append((f, desc, val, acc))

    # ESTRATEGIA 4: RAW (1232, 7418, 9426) - Intento Regex
    elif 'raw' in df.columns or 'raw_line' in df.columns:
        print("   -> Detectado formato: RAW (Intentando extracción inteligente)")
        col_raw = 'raw' if 'raw' in df.columns else 'raw_line'
        
        # Regex para buscar fechas tipo 13Ago2025 o 03/11/2024
        # Regex para buscar montos (con $ o ,)
        for _, row in df.iterrows():
            line = str(row[col_raw])
            
            # Buscar fecha
            date_match = re.search(r'(\d{1,2}[A-Za-z]{3}\d{4})|(\d{2}/\d{2}/\d{4})', line)
            # Buscar monto (ej: $7,760 o 100.000)
            amount_match = re.search(r'[\$]?\s?-?(\d{1,3}[,.])+\d{1,2}', line)
            
            f = None
            if date_match:
                f = parse_flexible_date(date_match.group(0))
            
            val = 0.0
            if amount_match:
                # Limpiar el match para que sea float
                val_str = amount_match.group(0)
                # Si tiene puntos como miles, quitarlos. Si comas son decimales, cambiar a punto.
                # (Asunción simple para COLOMBIA: miles=punto o coma, decimales=raro en extractos simples)
                # Mejor limpiamos todo lo que no sea digito o menos
                val = clean_amount(val_str)
                # Si dice DEVOLUCION o similar, el signo podría estar lejos, pero asumamos positivo salvo signo explicito
                if '-' in line and val > 0: val = -val
            
            desc = line.replace(date_match.group(0) if date_match else '', '').strip()
            # Quitar monto de descripcion tambien
            # desc = ... (simplifiquemos)
            
            acc = filename.split('.')[0] # Nombre del archivo como cuenta (ej: 1232)
            
            if f:
                records.append((f, desc, val, acc))

    # INSERCIÓN EN BD
    if not records:
        print("   ⚠️ No se pudieron extraer registros válidos.")
        return

    conn = get_db_connection()
    if not conn: return
    cur = conn.cursor()
    
    count = 0
    for rec in records:
        fecha, desc, monto, cuenta = rec
        
        # 1. Asegurar Cuenta
        # Buscamos el ID de tipo 'Bank Account' (asumimos ID 1 o buscamos)
        cur.execute("SELECT type_id FROM account_types WHERE type_name = 'Bank Account'")
        res = cur.fetchone()
        type_id = res[0] if res else 1 # Fallback a 1 si falla
        
        # Insertar cuenta si no existe (con los campos correctos)
        cur.execute("""
            INSERT INTO accounts (account_name, account_type_id, currency_code) 
            VALUES (%s, %s, 'COP') 
            ON CONFLICT (account_name) DO NOTHING
        """, (cuenta, type_id))
        
        # 2. Obtener ID Cuenta
        cur.execute("SELECT account_id FROM accounts WHERE account_name = %s", (cuenta,))
        acc_id = cur.fetchone()[0]
        
        # 3. Insertar Transacción (Evitar duplicados simples por fecha+monto+desc)
        # Idealmente usaríamos hash del archivo, pero por ahora simple
        try:
            cur.execute("""
                INSERT INTO transactions (account_id, date, amount, description, status)
                VALUES (%s, %s, %s, %s, 'CLEARED')
            """, (acc_id, fecha, monto, desc))
            count += 1
            
            # GATILLO DE ALERTA
            check_and_alert_transaction(monto, desc, cuenta, fecha)
            
        except Exception as e:
            print(f"Error insertando linea: {e}")
            conn.rollback()
            continue
            
    conn.commit()
    cur.close()
    conn.close()
    print(f"   ✅ Insertados {count} registros en cuenta '{records[0][3]}'.")


def main():
    print("🚀 Iniciando Universal Loader...")
    files = glob.glob(os.path.join(CSV_DIR, "*.csv"))
    if not files:
        print(f"❌ No se encontraron archivos en {CSV_DIR}")
        return

    for f in files:
        process_file(f)
    
    print("\n🏁 Proceso finalizado.")

if __name__ == "__main__":
    main()
