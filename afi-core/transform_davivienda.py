import json
from datetime import datetime

INPUT_FILE = "raw_davivienda.json"
OUTPUT_FILE = "import_data_dav.json"

def transform_data(input_data: dict) -> list:
    transformed_accounts = []
    
    bank_name = input_data.get("banco", "Unknown Bank")
    account_number = input_data.get("numero_cuenta", "").replace(" ", "")
    
    # Create a single account entry
    account_name = f"{bank_name} {account_number}" if account_number else bank_name
    
    all_transactions = []
    
    for extracto in input_data.get("extractos", []):
        periodo_str = extracto.get("periodo") # e.g., "NOVIEMBRE/2024"
        
        # Parse year and month from periodo_str
        try:
            month_name, year_str = periodo_str.split('/')
            year = int(year_str)
            # Map month name to number
            month_map = {
                "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
                "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
                "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12
            }
            month = month_map.get(month_name.upper())
            if not month:
                print(f"⚠️ Mes desconocido en periodo: {periodo_str}. Saltando.")
                continue
        except Exception as e:
            print(f"⚠️ Error parseando periodo '{periodo_str}': {e}. Saltando.")
            continue
            
        for mov in extracto.get("movimientos", []):
            fecha_str = mov.get("fecha") # e.g., "07-11" (day-month)
            try:
                day, mov_month = map(int, fecha_str.split('-'))
                
                # Use year from periodo, and month from transaction, unless transaction month is 
                # significantly different, then adjust year.
                # This handles cases where a period "DECEMBER/2024" might contain transactions from Jan 2025 (edge cases)
                current_year = year
                if mov_month == 1 and month == 12: # Dec statement with Jan transactions (next year)
                    current_year += 1
                elif mov_month == 12 and month == 1: # Jan statement with Dec transactions (prev year)
                    current_year -= 1

                full_date = datetime(current_year, mov_month, day).strftime("%Y-%m-%d")
            except Exception as e:
                print(f"⚠️ Error parseando fecha '{fecha_str}' en periodo '{periodo_str}': {e}. Saltando transacción.")
                continue
            
            payee_name = mov.get("descripcion", "Unknown Payee")
            # Combine document and oficina into notes if available
            notes_parts = []
            if mov.get("documento"):
                notes_parts.append(f"Doc: {mov['documento']}")
            if mov.get("oficina"):
                notes_parts.append(f"Oficina: {mov['oficina']}")
            notes = " | ".join(notes_parts) if notes_parts else ""

            all_transactions.append({
                "date": full_date,
                "amount": mov.get("valor"), # Amount is already float, json_ingest will convert to cents
                "payee_name": payee_name,
                "notes": notes
            })
            
    transformed_accounts.append({
        "account_name": account_name,
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
    except FileNotFoundError:
        print(f"❌ Error: El archivo de entrada '{INPUT_FILE}' no fue encontrado.")
    except json.JSONDecodeError as e:
        print(f"❌ Error de formato JSON en '{INPUT_FILE}': {e}")
    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")
