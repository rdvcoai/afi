import json
import httpx
import pandas as pd
import threading

BRIDGE_URL = "http://afi-whatsapp:3000"
CSV_FILE = "/app/consolidado_historia.csv"


def get_financial_audit():
    """Lee el CSV y devuelve un resumen básico de gasto."""
    try:
        df = pd.read_csv(CSV_FILE)
        if df.empty:
            return json.dumps({"total_spent": 0, "top_patterns": {}, "has_data": False})
        top_payees = df["descripcion"].value_counts().head(50).to_dict()
        total_spent = df["monto"].abs().sum()
        return json.dumps({"total_spent": float(total_spent), "top_patterns": top_payees, "has_data": True})
    except Exception as e:
        print(f"⚠️ Auditoría vacía o error leyendo CSV: {e}")
        return json.dumps({"total_spent": 0, "top_patterns": {}, "has_data": False})


def create_category_tool(name, group="Gastos Variables"):
    """Crea una categoría en Actual Budget."""
    print(f"🔧 TOOL: Creando categoría '{name}'")
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{BRIDGE_URL}/category/create",
                json={"name": name, "group_name": group if group else None},
            )
        if resp.status_code == 200:
            return f"Categoría '{name}' creada."
        return f"No se pudo crear categoría: {resp.text}"
    except Exception as e:
        print(f"⚠️ Error creando categoría: {e}")
        return f"Error creando categoría: {e}"


def categorize_payees_tool(category_name, keywords_list):
    """Movimientos masivos por keywords en segundo plano."""
    print(f"🔧 TOOL: Iniciando movimiento masivo para '{category_name}'")

    def _run_bulk_bg():
        try:
            with httpx.Client(timeout=120.0) as client:
                client.post(
                    f"{BRIDGE_URL}/category/bulk-categorize",
                    json={"category_name": category_name, "keywords_list": keywords_list},
                )
                print(f"✅ Background job terminado para {category_name}")
        except Exception as e:
            print(f"❌ Error en background job: {e}")

    try:
        t = threading.Thread(target=_run_bulk_bg, daemon=True)
        t.start()
        return f"Orden recibida. Moviendo transacciones a '{category_name}' en segundo plano. Puedes seguir conversando."
    except Exception as e:
        print(f"⚠️ Error lanzando background job: {e}")
        return f"Error lanzando movimiento masivo: {e}"


TOOLS_SCHEMA = [
    get_financial_audit,
    create_category_tool,
    categorize_payees_tool,
]
