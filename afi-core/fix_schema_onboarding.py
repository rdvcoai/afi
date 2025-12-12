from database import get_conn

def apply_fix():
    print("🚑 Fixing Database Schema (Adding missing columns)...")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_status VARCHAR(50) DEFAULT 'welcome';")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS archetype VARCHAR(50);")
                print("✅ Added 'onboarding_status' and 'archetype' columns to 'users' table.")
    except Exception as e:
        print(f"❌ Error fixing schema: {e}")

if __name__ == "__main__":
    apply_fix()
