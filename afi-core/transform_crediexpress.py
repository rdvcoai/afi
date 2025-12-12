import json
from datetime import datetime

INPUT_FILE = "raw_crediexpress.json"
OUTPUT_FILE = "import_data_cre.json"

MONTH_MAP = {
    "Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Ago": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12
}

def parse_spanish_date(date_str: str) -> str:
    # Format: "04 Dic 2024" or "05 Ene 2025"
    parts = date_str.split()
    if len(parts) != 3:
        return None
    day = int(parts[0])
    month_str = parts[1].replace(".", "").strip() # Handle abbreviations like "Ene."
    year = int(parts[2])
    
    month = MONTH_MAP.get(month_str)
    if not month:
        # Try title case
        month = MONTH_MAP.get(month_str.capitalize())
    
    if not month:
        return None
        
    return datetime(year, month, day).strftime("%Y-%m-%d")

def transform_data(input_data: dict) -> list:
    transformed_accounts = []
    
    data = input_data.get("crediexpress", {})
    bank_name = data.get("banco", "Unknown Bank")
    # "numero_credito": "590047390050353-2" -> "5900...353-2"
    credit_number = data.get("numero_credito", "").split("-")[0][-4:] # Last 4 digits? Or full?
    # Full is better for uniqueness
    credit_number_full = data.get("numero_credito", "")
    
    account_name = f"{bank_name} Crediexpress {credit_number_full}"
    
    all_transactions = []
    
    for extracto in data.get("extractos", []):
        for mov in extracto.get("movimientos", []):
            date_str = mov.get("fecha")
            date_iso = parse_spanish_date(date_str)
            if not date_iso:
                print(f"⚠️ Fecha inválida: {date_str}")
                continue
                
            desc = mov.get("descripcion", "Movimiento")
            doc = mov.get("documento", "")
            val = mov.get("valor", 0)
            
            # Crediexpress transactions (Payments) are usually positive inflows to the loan account (reducing debt).
            # If "valor" is positive in JSON, keep it positive.
            
            notes = f"Doc: {doc}" if doc else ""
            
            all_transactions.append({
                "date": date_iso,
                "amount": val,
                "payee_name": desc,
                "notes": notes
            })
            
    transformed_accounts.append({
        "account_name": account_name,
        "account_type": "credit", # Treat as liability
        "transactions": all_transactions
    })

    return transformed_accounts

if __name__ == "__main__":
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        
        transformed = transform_data(raw_data)
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(transformed, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Datos transformados y guardados en {OUTPUT_FILE}")
        print(f"   Cuenta: {transformed[0]['account_name']}")
        print(f"   Transacciones: {len(transformed[0]['transactions'])}")
    except FileNotFoundError:
        print(f"❌ Error: El archivo de entrada '{INPUT_FILE}' no fue encontrado.")
    except json.JSONDecodeError as e:
        print(f"❌ Error de formato JSON en '{INPUT_FILE}': {e}")
    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")
