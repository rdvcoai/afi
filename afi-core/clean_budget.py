import sys

from dotenv import load_dotenv

from db_ops import delete_all_accounts_and_transactions, list_accounts


def load_env() -> None:
    """Carga variables .env (opcional en ejecución local)."""
    try:
        load_dotenv()
    except Exception:
        pass


def main():
    load_env()
    try:
        accounts = list_accounts()
    except Exception as e:
        print(f"❌ No se pudieron listar cuentas en Postgres: {e}")
        sys.exit(1)

    if not accounts:
        print("✅ No hay cuentas para eliminar. Bóveda ya está vacía.")
        return

    print(f"🧹 Eliminando {len(accounts)} cuentas (se borran transacciones asociadas)...")
    try:
        delete_all_accounts_and_transactions()
    except Exception as e:
        print(f"   ❌ Error en limpieza: {e}")
        return

    print(f"🏁 Limpieza completa. Cuentas eliminadas: {len(accounts)}.")


if __name__ == "__main__":
    main()
