import os
from database import get_conn

def apply_rls():
    print("🔒 Locking down the Vault (Applying RLS)...")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # 1. Transactions
                print("   - Securing Transactions...")
                cur.execute("ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;")
                cur.execute("ALTER TABLE transactions FORCE ROW LEVEL SECURITY;") # Force owner (afi_user) to respect policy
                cur.execute("DROP POLICY IF EXISTS user_isolation_tx ON transactions;")
                cur.execute("""
                    CREATE POLICY user_isolation_tx ON transactions
                    USING (user_id = current_setting('app.current_user_id', true)::integer);
                """)

                # 2. Accounts
                print("   - Securing Accounts...")
                cur.execute("ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;")
                cur.execute("ALTER TABLE accounts FORCE ROW LEVEL SECURITY;")
                cur.execute("DROP POLICY IF EXISTS user_isolation_acc ON accounts;")
                cur.execute("""
                    CREATE POLICY user_isolation_acc ON accounts
                    USING (user_id = current_setting('app.current_user_id', true)::integer);
                """)

                # 3. Monthly Budgets
                print("   - Securing Budgets...")
                cur.execute("ALTER TABLE monthly_budgets ENABLE ROW LEVEL SECURITY;")
                cur.execute("ALTER TABLE monthly_budgets FORCE ROW LEVEL SECURITY;")
                cur.execute("DROP POLICY IF EXISTS user_isolation_budget ON monthly_budgets;")
                cur.execute("""
                    CREATE POLICY user_isolation_budget ON monthly_budgets
                    USING (user_id = current_setting('app.current_user_id', true)::integer);
                """)
                
                print("✅ RLS Applied successfully.")

    except Exception as e:
        print(f"❌ Error applying RLS: {e}")

if __name__ == "__main__":
    apply_rls()
