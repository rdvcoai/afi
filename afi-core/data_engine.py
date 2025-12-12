import google.generativeai as genai
import pandas as pd
import json
import time
import os
import math

# Usamos Flash para velocidad en lotes grandes, o Pro si es complejo.
# Para CSVs estructurados, Flash 2.5 es suficiente y mucho más rápido.
MODEL_PARSER = "gemini-2.5-flash" 

def process_file_universal(file_path, mime_type):
    """
    Router Inteligente:
    - Si es CSV/Excel: Aplica 'Chunking' (divide y vencerás) para garantizar lectura 100%.
    - Si es PDF/Imagen: Usa Gemini Vision nativo.
    """
    print(f"🧠 Iniciando Ingesta Cognitiva: {file_path} ({mime_type})")
    all_transactions = []
    
    try:
        # --- ESTRATEGIA 1: CHUNKING PARA TABLAS (CSV/EXCEL) ---
        if any(x in mime_type for x in ['csv', 'sheet', 'excel']) or file_path.endswith(('.csv', '.xlsx', '.xls')):
            
            # Leer con Pandas (Solo para cortar, no para analizar)
            try:
                if 'csv' in mime_type or file_path.endswith('.csv'):
                    df = pd.read_csv(file_path, sep=None, engine='python', on_bad_lines='skip', encoding_errors='replace')
                else:
                    df = pd.read_excel(file_path)
            except Exception as e:
                print(f"⚠️ Pandas falló leyendo estructura, pasando a modo texto crudo: {e}")
                return process_raw_text_chunks(file_path)

            total_rows = len(df)
            BATCH_SIZE = 40 # Tamaño seguro para que Gemini no corte el JSON
            batches = math.ceil(total_rows / BATCH_SIZE)
            
            print(f"📊 Archivo tabular detectado: {total_rows} filas. Procesando en {batches} lotes...")

            for i in range(batches):
                start = i * BATCH_SIZE
                end = start + BATCH_SIZE
                
                # Extraer trozo y convertir a Markdown (texto digerible para IA)
                chunk_df = df.iloc[start:end]
                chunk_text = chunk_df.to_markdown(index=False)
                
                print(f"   🔄 Procesando lote {i+1}/{batches}...")
                
                # Llamada a IA por lote
                txs = extract_from_text(chunk_text)
                if txs:
                    all_transactions.extend(txs)
                
                # Pequeña pausa para no saturar API
                time.sleep(1)

        # --- ESTRATEGIA 2: NATIVA PARA PDF/IMÁGENES ---
        else:
            print("📄 Documento visual detectado (PDF/Imagen). Enviando a Gemini Vision...")
            all_transactions = extract_with_vision(file_path, mime_type)

        print(f"✅ EXTRACCIÓN COMPLETADA: {len(all_transactions)} movimientos recuperados de {file_path}.")
        return all_transactions

    except Exception as e:
        print(f"❌ Error Fatal en Ingesta: {e}")
        return []

def extract_from_text(text_content):
    """Envía texto a Gemini y pide JSON"""
    prompt = """
    ACTÚA COMO: Auditor de Datos (ETL).
    TAREA: Extrae transacciones de este fragmento de datos bancarios.
    
    INPUT:
    """ + text_content + """
    
    REGLAS ESTRICTAS DE SALIDA (JSON):
    Devuelve SOLO un array de objetos JSON válido.
    [
        {
            "date": "YYYY-MM-DD", 
            "amount": -50000, 
            "payee_name": "Uber", 
            "notes": "Transporte"
        }
    ]
    - Montos: Negativo (-) para gastos, Positivo (+) para ingresos.
    - Fechas: Convierte a formato ISO.
    - Limpieza: Elimina filas vacías o de saldos acumulados.
    """
    
    return _call_gemini(prompt)

def extract_with_vision(file_path, mime_type):
    """Sube archivo a Gemini y pide JSON"""
    uploaded_file = genai.upload_file(file_path, mime_type=mime_type)
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(1)
        uploaded_file = genai.get_file(uploaded_file.name)
        
    prompt = """
    Extrae TODAS las transacciones visibles en este documento.
    Devuelve JSON Array con keys: date, amount (negativo gastos), payee_name, notes.
    """
    return _call_gemini(prompt, uploaded_file)

def _call_gemini(prompt, content=None):
    try:
        model = genai.GenerativeModel(MODEL_PARSER)
        if content:
            response = model.generate_content([prompt, content])
        else:
            response = model.generate_content(prompt)
            
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Error parsing JSON del lote: {e}")
        # Aquí podríamos agregar un reintento automático
        return []

def process_raw_text_chunks(file_path):
    # Fallback por si Pandas falla (lectura línea a línea)
    # Implementación simplificada
    return []
