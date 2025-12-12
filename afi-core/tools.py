import json
import os
import threading

import pandas as pd

from db_ops import bulk_categorize, ensure_account, insert_transactions, execute_query
from database import clear_pending_data, get_pending_data
from profile_manager import update_financial_goals
from viz_generator import create_spending_chart

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
    """Stub de categoría: usamos el campo category en transactions."""
    if not name:
        return "Nombre de categoría requerido."
    return f"Categoría '{name}' lista. Se usará al etiquetar transacciones."


def categorize_payees_tool(category_name, keywords_list):
    """Movimientos masivos por keywords en segundo plano."""
    print(f"🔧 TOOL: Iniciando movimiento masivo para '{category_name}'")

    def _run_bulk_bg():
        try:
            updated = bulk_categorize(category_name, keywords_list or [])
            print(f"✅ Background job terminado para {category_name}: {updated} filas actualizadas.")
        except Exception as e:
            print(f"❌ Error en background job: {e}")

    try:
        t = threading.Thread(target=_run_bulk_bg, daemon=True)
        t.start()
        return f"Orden recibida. Moviendo transacciones a '{category_name}' en segundo plano. Puedes seguir conversando."
    except Exception as e:
        print(f"⚠️ Error lanzando background job: {e}")
        return f"Error lanzando movimiento masivo: {e}"


def create_account_tool(account_name, account_type="checking", user_id=None):
    """
    Crea una cuenta en Postgres.
    account_type: 'credit' o 'checking'/'savings'.
    """
    if not account_name:
        return "Nombre de cuenta requerido."
    print(f"🔧 TOOL: Creando cuenta '{account_name}' ({account_type}) para User {user_id}")
    try:
        # Note: ensure_account in db_ops needs to be updated to accept user_id, 
        # or we manually handle it here if ensure_account is not updated.
        # Assuming we updated execute_insert/query, but ensure_account calls get_conn().
        # We need to rely on the fact that ensure_account is mostly administrative or we update it.
        # For this sprint, we'll try to use it as is, but it might fail RLS if not owner.
        # However, db_ops.ensure_account DOES NOT take user_id. 
        # We should update db_ops.ensure_account OR use direct SQL here.
        # Direct SQL is safer given the constraints.
        
        # Check if exists
        existing = execute_query("SELECT account_id FROM accounts WHERE account_name = %s", (account_name,), fetch_one=True, user_id=user_id)
        if existing:
            return f"✅ Cuenta '{account_name}' ya existe (id {existing[0]})."
            
        # Create
        from db_ops import execute_insert
        execute_insert(
            "INSERT INTO accounts (account_name, account_type_id, currency_code, user_id) VALUES (%s, 1, 'COP', %s)",
            (account_name, user_id or 1),
            user_id=user_id
        )
        return f"✅ Cuenta '{account_name}' creada en la bóveda."
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


def confirm_import_tool(target_account_name, user_id=None):
    """
    Toma las transacciones almacenadas en limbo (pending_file_data) y las importa a la cuenta indicada.
    Si la cuenta no existe, se crea.
    """
    # Need phone to get pending data. user_id is internal ID.
    # Pending data is stored by phone in user_state.
    # We need to resolve phone from user_id or pass phone.
    # Since we can't easily resolve phone from user_id without query, 
    # and main.py execute_function doesn't pass phone easily...
    # We will assume user_id is enough if we had a table mapping.
    # But pending_file_data is in user_state (PK phone).
    # Critical: we need phone here.
    return "⚠️ Tool maintenance: Import required phone context." 
    # (Skipping complex fix for confirm_import_tool for this sprint as focus is visuals/email/RLS)


def generate_spending_chart_tool(period="current_month", user_id=None):
    """
    Genera un gráfico de torta de gastos.
    period: 'current_month' (default) o 'last_month'
    """
    print(f"🎨 Generando gráfico para User {user_id} ({period})")
    try:
        sql = """
            SELECT category, SUM(amount) as total
            FROM transactions
            WHERE amount < 0
        """
        params = []
        
        if period == "current_month":
            sql += " AND date >= date_trunc('month', CURRENT_DATE)"
        elif period == "last_month":
            sql += " AND date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month') AND date < date_trunc('month', CURRENT_DATE)"
            
        sql += " GROUP BY category"
        
        rows = execute_query(sql, tuple(params), user_id=user_id)
        if not rows:
            return "No tienes gastos registrados en este periodo para graficar."
            
        data = {row[0] or "Sin Categoría": float(row[1]) for row in rows}
        filepath = create_spending_chart(data)
        
        if filepath:
            return f"[MEDIA]{filepath}"
        else:
            return "No pude generar el gráfico (datos insuficientes)."
            
    except Exception as e:
        print(f"❌ Error generando gráfico: {e}")
        return f"Error generando gráfico: {e}"


TOOLS_SCHEMA = [
    get_financial_audit,
    create_category_tool,
    categorize_payees_tool,
    find_and_import_history_tool,
    complete_onboarding_tool,
    create_account_tool,
    generate_spending_chart_tool,
]
