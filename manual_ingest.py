import pandas as pd
import requests
import time
import sys

BRIDGE_URL = "http://afi-whatsapp:3000/transaction/add"


def ingest(csv_file):
    df = pd.read_csv(csv_file)
    print(f"Inyectando {len(df)} registros...")

    for i, row in df.iterrows():
        payload = {
            "date": row['fecha'],
            "amount": float(row['monto']),
            "payee": str(row['descripcion'])[:100],
            "notes": f"Origen: {row['cuenta']}",
            "imported_id": f"HIST_{row['fecha']}_{i}_{abs(row['monto'])}"
        }
        try:
            requests.post(BRIDGE_URL, json=payload, timeout=2)
            if i % 100 == 0:
                print(f"Progreso: {i}/{len(df)}")
            time.sleep(0.01)
        except Exception as e:
            print(f"Error fila {i}: {e}")


if __name__ == "__main__":
    ingest(sys.argv[1])
