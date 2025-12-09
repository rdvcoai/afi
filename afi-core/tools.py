import json
import httpx
import pandas as pd
import threading
import os
from profile_manager import update_financial_goals
from data_engine import process_file

BRIDGE_URL = "http://afi-whatsapp:3000"
CSV_FILE = "/app/consolidado_historia.csv"
CSV_DIR = "/app/data/csv"


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


def create_account_tool(account_name, account_type="checking"):
    """
    Crea una cuenta en Actual Budget vía puente Node.
    account_type: 'credit' o 'checking'/'savings'.
    """
    if not account_name:
        return "Nombre de cuenta requerido."
    print(f"🔧 TOOL: Creando cuenta '{account_name}' ({account_type})")
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{BRIDGE_URL}/accounts",
                json={"name": account_name, "type": account_type, "balance": 0},
            )
            resp.raise_for_status()
        return f"✅ Cuenta '{account_name}' creada exitosamente."
    except Exception as e:
        print(f"⚠️ Error creando cuenta: {e}")
        return f"❌ Error técnico creando cuenta: {e}"


def find_and_import_history_tool(account_name):
    """
    Busca CSVs en /app/data/csv que coincidan con el nombre y reporta hallazgos.
    (Placeholder de importación; ajuste según formato de CSV.)
    """
    if not account_name:
        return "Nombre de cuenta requerido para buscar historial."
    if not os.path.exists(CSV_DIR):
        return f"No existe el directorio de CSVs ({CSV_DIR})."

    matches = [f for f in os.listdir(CSV_DIR) if account_name.lower() in f.lower() and f.lower().endswith(".csv")]
    if not matches:
        return f"No encontré historial para {account_name} en {CSV_DIR}."

    return f"Encontré {len(matches)} archivo(s) para {account_name}: {', '.join(matches)}. (Importación automática pendiente de formato definitivo.)"


def complete_onboarding_tool(summary=None):
    """Finaliza onboarding y activa perfil admin."""
    phone = os.getenv("ADMIN_PHONE")
    if phone and summary:
        try:
            update_financial_goals(phone, summary)
        except Exception as e:
            print(f"⚠️ No se pudo actualizar metas: {e}")
    return f"Perfil guardado y activado. Resumen: {summary or 'Perfil listo.'}"


def import_history_from_file_tool(account=None, file_name_in_server=None):
    """
    Importa transacciones desde un archivo existente en /app/data/csv.
    Se encarga de asegurar/crear la cuenta y luego llamar al puente.
    """
    csv_dir = "/app/data/csv"
    if not file_name_in_server:
        return "❌ Especifica el nombre del archivo a importar."
    file_path = os.path.join(csv_dir, file_name_in_server)
    if not os.path.exists(file_path):
        return f"❌ El archivo {file_name_in_server} no existe en {csv_dir}."
    if not account:
        return "❌ Especifica la cuenta destino."

    transactions = process_file(file_path, "text/csv")
    if not transactions:
        return "⚠️ El archivo existe pero no pude extraer transacciones válidas. Revisa el formato."

    try:
        with httpx.Client(timeout=30.0) as client:
            # Crear/asegurar cuenta y obtener ID
            resp_acct = client.post(f"{BRIDGE_URL}/accounts", json={"name": account, "type": "checking"})
            resp_acct.raise_for_status()
            account_id = resp_acct.json().get("id")

            resp = client.post(
                f"{BRIDGE_URL}/transactions/import",
                json={"accountId": account_id, "transactions": transactions},
            )
            resp.raise_for_status()
            return f"✅ ÉXITO: Se importaron {len(transactions)} movimientos a la cuenta {account}."
    except Exception as e:
        return f"❌ Error enviando datos a Actual: {e}"


def confirm_import_tool(target_account_name):
    """
    Toma las transacciones almacenadas en limbo (pending_file_data) y las importa a la cuenta indicada.
    Si la cuenta no existe, se crea.
    """
    phone = os.getenv("ADMIN_PHONE")
    if not target_account_name:
        return "⚠️ Debes indicar el nombre de la cuenta destino."
    txs = get_pending_data(phone)
    if not txs:
        return "⚠️ No tengo datos pendientes. Reenvía el archivo primero."

    try:
        with httpx.Client(timeout=30.0) as client:
            resp_acct = client.post(f"{BRIDGE_URL}/accounts", json={"name": target_account_name, "type": "checking"})
            resp_acct.raise_for_status()
            account_id = resp_acct.json().get("id")

            resp_imp = client.post(
                f"{BRIDGE_URL}/transactions/import",
                json={"accountId": account_id, "transactions": txs},
            )
            resp_imp.raise_for_status()
            clear_pending_data(phone)
            return f"✅ Importación completada: {len(txs)} movimientos en **{target_account_name}**."
    except Exception as e:
        return f"❌ Error técnico: {e}"


TOOLS_SCHEMA = [
    get_financial_audit,
    create_category_tool,
    categorize_payees_tool,
    find_and_import_history_tool,
    complete_onboarding_tool,
    import_history_from_file_tool,
    create_account_tool,
]
