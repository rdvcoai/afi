from database import get_conn

def get_user_profile(phone):
    """Obtiene el perfil del usuario o crea uno básico si no existe"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT phone, name, role, profile_status, financial_goals FROM users WHERE phone = %s", (phone,))
            row = cur.fetchone()
            if row:
                return {
                    "phone": row[0], "name": row[1], "role": row[2], 
                    "status": row[3], "goals": row[4]
                }
            return None

def update_financial_goals(phone, goals_summary):
    """Actualiza las metas financieras aprendidas durante la charla"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET financial_goals = %s, profile_status = 'active' WHERE phone = %s", (goals_summary, phone))

def is_admin(phone):
    profile = get_user_profile(phone)
    return profile and profile['role'] == 'admin'
