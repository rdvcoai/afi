import os
import psycopg2
from database import get_conn

def run_sprint16_updates():
    print("🚀 Starting Sprint 16 Database Updates...")
    
    # 1. Tabula Rasa (Clean Slate)
    print("🧹 Executing Tabula Rasa (Data Wipe)...")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Tabula Rasa SQL with RESTART IDENTITY to handle sequences automatically
                # We do them one by one to be safe, or we could list them all.
                # However, RESTART IDENTITY on one might affect others if cascaded, 
                # but explicit is better.
                
                tables = ["transactions", "accounts", "sessions", "otps", "users"]
                for table in tables:
                    print(f"   - Truncating {table}...")
                    # Check if table exists first to avoid errors? No, prompt implies they exist.
                    # Use RESTART IDENTITY to reset sequences.
                    cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;")

                print("✅ Tabula Rasa complete (Data wiped, Sequences reset).")

                # 2. Budget Engine (Schema Upgrade)
                print("🏗️ Building Budget Engine Schema...")
                
                # Master Categories
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS master_categories (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(50) UNIQUE NOT NULL,
                        type VARCHAR(20) NOT NULL
                    );
                """)
                
                # Monthly Budgets
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS monthly_budgets (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        category_id INTEGER REFERENCES master_categories(id),
                        month DATE NOT NULL,
                        amount_limit DECIMAL(15,2) NOT NULL DEFAULT 0,
                        UNIQUE(user_id, category_id, month)
                    );
                """)
                
                # Link Transactions to Master Categories
                cur.execute("""
                    ALTER TABLE transactions 
                    ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES master_categories(id);
                """)
                
                print("✅ Budget Engine Schema applied.")

    except Exception as e:
        print(f"❌ Error during update: {e}")
        # Re-raise to signal failure
        raise e

if __name__ == "__main__":
    run_sprint16_updates()