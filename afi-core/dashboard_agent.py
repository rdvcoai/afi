import os
import google.generativeai as genai

# Configuración
API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=API_KEY)

DASHBOARD_PATH = "/app/dashboard_code/app.py"

def generate_dashboard_v6():
    print("🎨 AFI está reparando tu Dashboard V6 (st.cache_resource)...")
    
    prompt = """
ACTÚA COMO: Desarrollador Senior de Streamlit (Python).

OBJETIVO: Reparar 'app.py' que falló por un error de caché de Streamlit.

ERROR ESPECÍFICO A CORREGIR:
- `streamlit.runtime.caching.cache_errors.UnserializableReturnValueError`
- CORRECCIÓN: Para la función `get_db_connection()`, DEBES usar `@st.cache_resource` en lugar de `@st.cache_data`. `st.cache_resource` es para objetos no serializables como conexiones de base de datos.

ESQUEMA DE BASE DE DATOS EXACTO (NO ALUCINES, USA ESTOS NOMBRES):
- Table 'transactions': transaction_id (PK), date, amount, description, category, account_id (FK).
- Table 'accounts': account_id (PK), account_name, account_type_id (FK).
- Table 'account_types': type_id (PK), type_name, classification (ASSET/LIABILITY).

INSTRUCCIONES SQL CRÍTICAS (DEBES USAR ESTA CONSULTA COMO BASE PARA OBTENER LAS TRANSACCIONES):
SELECT 
    t.transaction_id, 
    t.date, 
    t.amount, 
    t.description, 
    t.category, 
    a.account_name, 
    at.type_name,
    at.classification
FROM transactions t 
JOIN accounts a ON t.account_id = a.account_id 
JOIN account_types at ON a.account_type_id = at.type_id
ORDER BY t.date DESC;

REQUISITOS FUNCIONALES:
1. **Login Seguro:** Al inicio de la aplicación, pide una contraseña (`st.text_input("Contraseña", type="password")`). Valida contra `os.getenv('DB_PASS')`. Si es incorrecta, usa `st.error("Contraseña incorrecta")` y `st.stop()`.
2. **Moneda y Localización:** Pesos Colombianos (COP). Formato: `f"${valor:,.0f}"`.
3. **KPIs:** Patrimonio Neto, Liquidez, Deuda Total.
4. **Visualización:** Gráfico de Línea (sin `shape='spline'` para evitar errores de Plotly) y Treemap (con manejo de nulos).
5. **No `dotenv`:** Asegurarse de que no se use `dotenv` ni `load_dotenv()`.

SALIDA:
Solo código Python.
"""
    
    try:
        model = genai.GenerativeModel("models/gemini-2.5-pro")
        response = model.generate_content(prompt)
        code = response.text.replace("```python", "").replace("```", "").strip()
        
        with open(DASHBOARD_PATH, "w") as f:
            f.write(code)
        
        print("✅ Dashboard V6 Generado (st.cache_resource).")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    generate_dashboard_v6()