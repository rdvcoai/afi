import os
import json
import google.generativeai as genai
from db_ops import execute_insert, execute_query

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def get_user_state(phone):
    """Obtiene estado o crea usuario nuevo (post-wipe)"""
    res = execute_query("SELECT id, onboarding_status, archetype FROM users WHERE phone = %s", (phone,), fetch_one=True)
    if res:
        return {"id": res[0], "status": res[1], "archetype": res[2]}
    else:
        # Crear usuario nuevo
        execute_insert("INSERT INTO users (phone, onboarding_status) VALUES (%s, 'welcome')", (phone,))
        # Recuperar ID generado
        new_user = execute_query("SELECT id FROM users WHERE phone = %s", (phone,), fetch_one=True)
        return {"id": new_user[0], "status": "welcome", "archetype": None}

def update_status(phone, status, archetype=None):
    sql = "UPDATE users SET onboarding_status = %s"
    params = [status]
    if archetype:
        sql += ", archetype = %s"
        params.append(archetype)
    sql += " WHERE phone = %s"
    params.append(phone)
    execute_insert(sql, tuple(params))

def create_initial_budget(user_id, income_guess):
    """Crea un presupuesto base según la regla 50/30/20 aproximada"""
    # 1. Obtener IDs de categorías maestras (Asumiendo que existen por el Sprint 16)
    cats = execute_query("SELECT id, name FROM master_categories")
    cat_map = {name: id for id, name in cats}
    
    # Presupuesto simple: 50% Vivienda/Fijos, 30% Ocio, 20% Ahorro
    # Ajustar según categorías reales que tengas en master_categories
    if 'Vivienda' in cat_map:
        execute_insert("INSERT INTO monthly_budgets (user_id, category_id, month, amount_limit) VALUES (%s, %s, CURRENT_DATE, %s) ON CONFLICT (user_id, category_id, month) DO UPDATE SET amount_limit = EXCLUDED.amount_limit", (user_id, cat_map['Vivienda'], income_guess * 0.4))
    if 'Mercado' in cat_map:
        execute_insert("INSERT INTO monthly_budgets (user_id, category_id, month, amount_limit) VALUES (%s, %s, CURRENT_DATE, %s) ON CONFLICT (user_id, category_id, month) DO UPDATE SET amount_limit = EXCLUDED.amount_limit", (user_id, cat_map['Mercado'], income_guess * 0.15))
    if 'Transporte' in cat_map:
        execute_insert("INSERT INTO monthly_budgets (user_id, category_id, month, amount_limit) VALUES (%s, %s, CURRENT_DATE, %s) ON CONFLICT (user_id, category_id, month) DO UPDATE SET amount_limit = EXCLUDED.amount_limit", (user_id, cat_map['Transporte'], income_guess * 0.10)) # Asumiendo un 10%
    if 'Ocio' in cat_map:
        execute_insert("INSERT INTO monthly_budgets (user_id, category_id, month, amount_limit) VALUES (%s, %s, CURRENT_DATE, %s) ON CONFLICT (user_id, category_id, month) DO UPDATE SET amount_limit = EXCLUDED.amount_limit", (user_id, cat_map['Ocio'], income_guess * 0.15)) # Asumiendo un 15%
    if 'Ahorro' in cat_map:
        execute_insert("INSERT INTO monthly_budgets (user_id, category_id, month, amount_limit) VALUES (%s, %s, CURRENT_DATE, %s) ON CONFLICT (user_id, category_id, month) DO UPDATE SET amount_limit = EXCLUDED.amount_limit", (user_id, cat_map['Ahorro'], income_guess * 0.20)) # Asumiendo un 20%


def process_onboarding(user_query, phone):
    state = get_user_state(phone)
    user_id = state["id"]
    status = state["status"]
    
    if status == "complete": return None

    # --- FLUJO DE ENTREVISTA ---
    
    if status == "welcome":
        update_status(phone, "interview_1")
        return {
            "answer": "👋 ¡Hola! Soy AFI. Veo que eres nuevo aquí. Mi base de datos está limpia y lista para escribir tu historia financiera.\n\nPara configurar tu tablero, necesito saber: **¿Cuál es tu ingreso mensual aproximado (para calibrar los presupuestos)?**",
            "viz_type": "text"
        }

    if status == "interview_1":
        # Intentar extraer número del ingreso
        try:
            # Lógica simple o usar Gemini para extraer monto
            income = int(''.join(filter(str.isdigit, user_query)))
            if income <= 0:
                raise ValueError("Income must be positive.")
            create_initial_budget(user_id, income)
            msg = f"Entendido. He creado un presupuesto base de ${income:,.0f} (que afinaremos luego).\n\nAhora, calibremo el psicólogo: **¿El dinero para ti es SEGURIDAD, LIBERTAD o ESTATUS?**"
            update_status(phone, "interview_2")
        except ValueError:
            msg = "No entendí el número. ¿Podrías escribir solo el monto aproximado de tus ingresos? (Ej: 5000000)"
        except Exception as e:
            msg = f"Hubo un error al procesar tu ingreso. Por favor, intenta de nuevo. Error: {e}"
        
        return {"answer": msg, "viz_type": "text"}

    if status == "interview_2":
        # Perfilado Final con Gemini
        prompt = f"""
        ACTÚA COMO: Psicólogo Financiero.
        USUARIO VALORA: {user_query}.
        ASIGNA ARQUETIPO: (Ahorrador, Gastador, Inversor, Guardián).
        DEFINE ESTRATEGIA: Una frase corta.
        SALIDA JSON: {{ "archetype": "...", "strategy": "..." }}
        """
        model = genai.GenerativeModel("gemini-1.5-flash")
        try:
            res = json.loads(model.generate_content(prompt).text.replace("```json",""""").replace("```","""""))
            update_status(phone, "complete", archetype=res['archetype'])
            return {
                "answer": f"Perfil: **{res['archetype']}**. Estrategia: {res['strategy']}.\n\n✅ **Sistema Configurado.**\nYa puedes subir tus extractos o registrar gastos por voz.",
                "viz_type": "text"
            }
        except Exception as e:
             print(f"Error extracting archetype or strategy: {e}. Defaulting to 'Explorador'.")
             update_status(phone, "complete", archetype="Explorador")
             return {"answer": "¡Listo! Perfil configurado. Ya puedes usar el sistema.", "viz_type": "text"}

    return None