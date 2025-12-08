import pandas as pd
import os
import re
from datetime import datetime

# Configuración
CSV_FOLDER = "./csv"
OUTPUT_FILE = "consolidado_historia.csv"
DEFAULT_YEAR = "2025"

MESES = {
    'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04', 'may': '05', 'jun': '06',
    'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dic': '12',
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04', 'mayo': '05', 'junio': '06',
    'julio': '07', 'agosto': '08', 'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
}


def clean_amount(val):
    try:
        val = str(val).replace('$', '').replace(' ', '')
        # Detectar si usa punto como miles (caso 1232.csv) o coma
        if val.count('.') > 1 or ('.' in val and ',' in val and val.find('.') < val.find(',')):
            val = val.replace('.', '').replace(',', '.')
        else:
            val = val.replace(',', '')
        return float(val)
    except Exception:
        return 0.0


def parse_spanish_date(date_str):
    try:
        date_str = date_str.lower().strip()
        for k, v in MESES.items():
            if k in date_str:
                date_str = date_str.replace(k, v)
                break
        date_str = re.sub(r'[^\d/]', '', date_str)
        if len(date_str) == 8:  # 22052025 -> 2025-05-22
            return f"{date_str[4:]}-{date_str[2:4]}-{date_str[0:2]}"
        return date_str
    except Exception:
        return None


def process_generic_raw(df, account_name):
    # Procesa 9426.csv y 7418.csv
    rows = []
    for line in df.iloc[:, 0]:
        match = re.search(r'(\d{2}[A-Za-z]{3}\d{4}).*?(\$[\d,]+)', str(line))
        if match:
            f, m = match.groups()
            rows.append({
                'fecha': parse_spanish_date(f),
                'monto': -abs(clean_amount(m)),
                'descripcion': line.replace(f, '').replace(m, '').strip(),
                'cuenta': account_name
            })
    return pd.DataFrame(rows)


def process_daviplata(df):
    rows = []
    for _, row in df.iterrows():
        d, m = row['fecha'].split('/')
        rows.append({
            'fecha': f"{DEFAULT_YEAR}-{m}-{d}",
            'monto': float(row['valor']),
            'descripcion': str(row['descripcion']) + " " + str(row['destino'] or ''),
            'cuenta': 'DaviPlata'
        })
    return pd.DataFrame(rows)


def main():
    all_data = []
    processors = {
        '9426.csv': lambda df: process_generic_raw(df, 'Cuenta 9426'),
        '7418.csv': lambda df: process_generic_raw(df, 'Cuenta 7418'),
        'daviplata.csv': process_daviplata,
        'nequi.csv': lambda df: df.assign(fecha=pd.to_datetime(df['fecha'], dayfirst=True).dt.strftime('%Y-%m-%d'), monto=df['valor'], cuenta='Nequi'),
        'rappicard_final_simple.csv': lambda df: df.assign(monto=-df['valor'].abs(), cuenta='RappiCard').rename(columns={'concepto': 'descripcion'}),
        'cuenta2029_final_simple.csv': lambda df: df.assign(monto=df['valor'], cuenta='Cuenta 2029'),
        'crediexpress.csv': lambda df: df.assign(fecha=df['fecha'].apply(parse_spanish_date), monto=-df['valor'].abs(), descripcion=df['clase'] + " " + df['operacion'].astype(str), cuenta='CrediExpress'),
        '1232.csv': lambda df: pd.DataFrame([{
            'fecha': datetime.strptime(re.search(r'(\d{2}/\d{2}/\d{4})', r['raw_line']).group(1), "%d/%m/%Y").strftime("%Y-%m-%d"),
            'monto': -clean_amount(re.search(r'\$\s?([\d\.]+)', r['raw_line']).group(1)),
            'descripcion': r['raw_line'], 'cuenta': 'Cuenta 1232'
        } for _, r in df.iterrows() if re.search(r'\$\s?([\d\.]+)', r['raw_line'])])
    }

    for f, func in processors.items():
        if os.path.exists(os.path.join(CSV_FOLDER, f)):
            print(f"Procesando {f}...")
            try:
                df = pd.read_csv(os.path.join(CSV_FOLDER, f))
                all_data.append(func(df)[['fecha', 'monto', 'descripcion', 'cuenta']])
            except Exception as e:
                print(f"Error {f}: {e}")

    pd.concat(all_data).to_csv(OUTPUT_FILE, index=False)
    print("✅ Maestro generado.")


if __name__ == "__main__":
    main()
