import sys
import time

import pandas as pd

from db_ops import ensure_account, insert_transactions


def ingest(csv_file):
    df = pd.read_csv(csv_file)
    print(f"Inyectando {len(df)} registros en Postgres...")

    per_account = {}
    for _, row in df.iterrows():
        account_name = row.get("cuenta") or "Cuenta CSV"
        payload = {
            "date": row.get("fecha"),
            "amount": float(row.get("monto", 0)),
            "description": str(row.get("descripcion") or row.get("payee_name") or "Movimiento")[:200],
            "import_source": f"manual:{csv_file}",
        }
        per_account.setdefault(account_name, []).append(payload)

    total_inserted = 0
    for account_name, txs in per_account.items():
        try:
            account_id = ensure_account(account_name)
            if not account_id:
                print(f"⚠️ No pude asegurar la cuenta {account_name}")
                continue
            inserted = insert_transactions(account_id, txs, import_source=f"manual:{csv_file}")
            total_inserted += inserted
            print(f"   ✅ {inserted} movimientos en {account_name}")
            time.sleep(0.01)
        except Exception as e:
            print(f"Error importando cuenta {account_name}: {e}")

    print(f"🏁 Importación completa. Total movimientos: {total_inserted}")


if __name__ == "__main__":
    ingest(sys.argv[1])
