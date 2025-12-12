import json
import os
import httpx
import time

# Configuração
# Using /app/import_data.json to avoid permission issues in /app/data volume if it's root-owned
DATA_FILE = "/app/import_data.json" 
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://afi-whatsapp:3000")

def run_ingest():
    print("🚀 Iniciando Ingesta Quirúrgica vía JSON...")
    
    if not os.path.exists(DATA_FILE):
        print(f"❌ Error: No encuentro el archivo {DATA_FILE}")
        return

    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error leyendo JSON: {e}")
        return

    with httpx.Client(timeout=30.0) as client:
        for entry in data:
            account_name = entry.get('account_name')
            account_type = entry.get('account_type', 'checking') # Default to checking, allow override
            transactions = entry.get('transactions', [])
            
            print(f"\n📂 Procesando: {account_name} ({len(transactions)} movimientos)")

            # 1. Obtener o Crear Cuenta (Idempotente)
            account_id = None
            try:
                # Primero listamos cuentas para ver si existe
                resp_list = client.get(f"{BRIDGE_URL}/accounts")
                if resp_list.status_code == 200:
                    existing_accounts = resp_list.json()
                    for acc in existing_accounts:
                        if acc.get('name', '').lower() == account_name.lower():
                            account_id = acc.get('id')
                            print(f"   ✅ Cuenta existente detectada. ID: {account_id}")
                            break
                
                if not account_id:
                    # Intentamos crear cuenta
                    resp = client.post(f"{BRIDGE_URL}/accounts", json={
                        "name": account_name,
                        "type": account_type, 
                        "balance": 0
                    })
                    
                    if resp.status_code in [200, 201]:
                        account_id = resp.json().get('id') or resp.json().get('success') # Adjust based on bridge response
                        # My bridge returns { success: true, id: "..." }
                        if isinstance(account_id, bool): # If it returned success: true but id separately
                             account_id = resp.json().get('id')
                        print(f"   ✅ Cuenta creada. ID: {account_id}")
                    else:
                        print(f"   ⚠️ Alerta: No se pudo crear cuenta. Status: {resp.status_code} - {resp.text}")
                        continue
            except Exception as e:
                print(f"   ❌ Error conexión Bridge (Cuentas): {e}")
                continue

            # 2. Inyectar Transacciones
            if transactions and account_id:
                # Normalize amounts to integers (cents) if they are floats
                normalized_txs = []
                for tx in transactions:
                    amount = tx.get('amount')
                    if isinstance(amount, float):
                        tx['amount'] = int(round(amount * 100))
                    normalized_txs.append(tx)

                try:
                    # Lote de 100 para no saturar
                    batch_size = 100
                    for i in range(0, len(normalized_txs), batch_size):
                        batch = normalized_txs[i:i + batch_size]
                        print(f"   ➡️ Enviando lote {i} - {i+len(batch)}...")
                        resp_tx = client.post(f"{BRIDGE_URL}/transactions/import", json={
                            "accountId": account_id,
                            "transactions": batch
                        })
                        if resp_tx.status_code == 200:
                            print(f"      ✅ Insertados")
                        else:
                            print(f"      ❌ Fallo ({resp_tx.status_code}: {resp_tx.text})")
                except Exception as e:
                    print(f"   ❌ Error inyectando transacciones: {e}")

    print("\n🏁 Proceso finalizado.")

if __name__ == "__main__":
    run_ingest()