import asyncio
import os
from database import get_conn
from backup_manager import run_backup

async def verify():
    print("🔍 Verifying Sprint 16 DoD...")
    
    # 1. Verify DB is Empty (Tabula Rasa)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM transactions;")
            tx_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users;")
            user_count = cur.fetchone()[0]
            
            if tx_count == 0 and user_count == 0:
                print("✅ DoD: Database is empty (Tabula Rasa successful).")
            else:
                print(f"❌ DoD: Database NOT empty. Tx: {tx_count}, Users: {user_count}")

    # 2. Verify Budget Tables
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.master_categories');")
            has_cats = cur.fetchone()[0]
            cur.execute("SELECT to_regclass('public.monthly_budgets');")
            has_budgets = cur.fetchone()[0]
            
            if has_cats and has_budgets:
                print("✅ DoD: Budget tables exist.")
            else:
                print("❌ DoD: Budget tables missing.")

    # 3. Verify Backup
    print("📦 Testing Backup Trigger...")
    try:
        await run_backup()
        print("✅ DoD: Backup executed successfully (Check OneDrive).")
    except Exception as e:
        print(f"❌ DoD: Backup failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify())
