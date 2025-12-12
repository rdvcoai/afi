import os
import json
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

CORE_URL = os.getenv("CORE_URL", "http://localhost:8080")

st.set_page_config(page_title="AFI Console", layout="wide", page_icon="🧠")

# --- Session State ---
if "auth_stage" not in st.session_state:
    st.session_state["auth_stage"] = "phone"
if "auth_phone" not in st.session_state:
    st.session_state["auth_phone"] = ""
if "auth_token" not in st.session_state:
    st.session_state["auth_token"] = None
if "messages" not in st.session_state:
    st.session_state["messages"] = []  # list of {role, content}
if "current_view" not in st.session_state:
    st.session_state["current_view"] = None
if "last_error" not in st.session_state:
    st.session_state["last_error"] = ""


# --- API helpers ---
def request_otp(phone: str) -> Optional[str]:
    try:
        r = requests.post(f"{CORE_URL}/auth/request-otp", json={"phone": phone}, timeout=10)
        if r.ok:
            return None
        return r.json().get("detail")
    except Exception as e:
        return f"Error de conexión: {e}"


def verify_otp(phone: str, code: str) -> Dict[str, Optional[str]]:
    try:
        r = requests.post(f"{CORE_URL}/auth/verify-otp", json={"phone": phone, "code": code}, timeout=10)
        if r.ok:
            data = r.json()
            return {"token": data.get("token"), "error": None}
        return {"token": None, "error": r.json().get("detail")}
    except Exception as e:
        return {"token": None, "error": f"Error de conexión: {e}"}


def call_core_api(question: str) -> Dict:
    payload = {
        "question": question,
        "token": st.session_state.get("auth_token"),
        "history": st.session_state.get("messages") or [],
    }
    try:
        r = requests.post(f"{CORE_URL}/chat/query", json=payload, timeout=25)
        if r.status_code == 200:
            return r.json()
        else:
            # st.error(f"🔥 Error del Núcleo ({r.status_code}): {r.text}")
            return {"answer": f"Error del sistema: {r.status_code}", "viz_type": "text"}
    except Exception as e:
        # st.error(f"❌ Error de Conexión: {str(e)}")
        return {"answer": "No se pudo conectar con el cerebro de AFI.", "viz_type": "text"}


# --- Render helpers ---
def safe_parse(data):
    """Asegura que data sea un Diccionario, no un String JSON"""
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            # Intentar limpiar comillas simples que a veces llegan de Python str()
            if data.strip().startswith("{") and "'" in data:
                import ast
                return ast.literal_eval(data)
            return json.loads(data)
        except:
            return {"answer": data, "viz_type": "text"} # Fallback a texto plano
    return {"answer": "", "viz_type": "none"}

def render_payload(raw_data):
    """Renderizador Maestro"""
    data = safe_parse(raw_data)
    
    # 1. TEXTO (La voz de AFI)
    # Solo mostramos el texto si NO es nulo
    answer = data.get("answer", "")
    if answer and answer != "None":
        st.markdown(f"{answer}")

    # 2. VISUALES
    viz_type = data.get("viz_type")
    
    if viz_type == "text" or viz_type is None:
        return

    # Si hay datos para gráficos
    rows = data.get("data", [])
    if not rows:
        return # No pintar gráficos vacíos

    df = pd.DataFrame(rows)
    
    if viz_type == "bar_chart":
        st.plotly_chart(px.bar(df, x=df.columns[0], y=df.columns[1], title=data.get("title")), use_container_width=True)
    elif viz_type == "line_chart":
        st.plotly_chart(px.line(df, x=df.columns[0], y=df.columns[1], title=data.get("title")), use_container_width=True)
    elif viz_type == "metric":
        val = df.iloc[0, 1] if not df.empty else 0
        st.metric(label=data.get("title"), value=f"${val:,.0f}")
    elif viz_type == "table":
        st.dataframe(df, use_container_width=True)

def show_empty_state_ui():
    """Lo que se muestra cuando el sistema es nuevo"""
    st.info("👋 **¡Bienvenido a AFI!** Tu Bóveda está lista pero vacía.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Paso 1: Configura")
        st.markdown("Habla con el chat a la izquierda para definir tu perfil.")
    with col2:
        st.markdown("### Paso 2: Ingesta")
        st.markdown("Arrastra tus extractos PDF/CSV o reenvía facturas a tu correo.")
    
    st.warning("⚠️ No verás gráficos hasta que registres tu primer movimiento.")


# --- Auth UI ---
def show_login_screen():
    st.title("🔐 Acceso Seguro AFI")
    st.caption("Ingresa tu teléfono y valida el código enviado a tu WhatsApp.")

    if st.session_state["auth_stage"] == "phone":
        countries = [
            ("🇨🇴 Colombia (+57)", "+57"),
            ("🇲🇽 México (+52)", "+52"),
            ("🇦🇷 Argentina (+54)", "+54"),
            ("🇨🇱 Chile (+56)", "+56"),
            ("🇵🇪 Perú (+51)", "+51"),
            ("🇪🇸 España (+34)", "+34"),
        ]
        country_label, country_code = st.selectbox(
            "País", countries, index=0, format_func=lambda x: x[0]
        )
        phone_number = st.text_input("Número de teléfono (solo dígitos)", value="")
        if st.button("Enviar código", type="primary"):
            digits_only = "".join(ch for ch in phone_number if ch.isdigit())
            full_phone = f"{country_code}{digits_only}"
            if not digits_only:
                st.session_state["last_error"] = "Ingresa un número de teléfono válido."
            else:
                err = request_otp(full_phone)
                if err:
                    st.session_state["last_error"] = err
                else:
                    st.session_state["auth_phone"] = full_phone
                    st.session_state["auth_stage"] = "otp"
                    st.success("Código enviado. Revisa tu WhatsApp.")
                    st.rerun()

    elif st.session_state["auth_stage"] == "otp":
        st.write(f"Código enviado a: **{st.session_state['auth_phone']}**")
        code = st.text_input("Ingresa el código de 6 dígitos", max_chars=6)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Validar código", type="primary"):
                result = verify_otp(st.session_state["auth_phone"], code)
                if result.get("token"):
                    st.session_state["auth_token"] = result["token"]
                    st.session_state["auth_stage"] = "ready"
                    st.session_state["messages"] = []
                    st.session_state["current_view"] = None
                    st.rerun()
                else:
                    st.session_state["last_error"] = result.get("error") or "Código inválido."
        with col2:
            if st.button("Reenviar código"):
                err = request_otp(st.session_state["auth_phone"])
                if err:
                    st.session_state["last_error"] = err
                else:
                    st.success("Código reenviado.")

    if st.session_state["last_error"]:
        st.error(st.session_state["last_error"])


def render_executive_summary():
    st.title("🚀 Resumen Ejecutivo")
    
    # 1. Consultar estado de datos
    try:
        # Pedimos al core un chequeo rápido
        summary = call_core_api("Dame un resumen ejecutivo con patrimonio total, gastos del mes, deuda y tendencia mensual.")
        data = safe_parse(summary)
        
        # 2. DETECTOR DE VACÍO
        text = str(data.get("answer", "")).lower()
        # Palabras clave que indican que el bot no encontró nada
        if "no encontré datos" in text or "no hay transacciones" in text or "no tengo información" in text:
             # Doble check: si tampoco hay data tabular
             if not data.get("data"):
                 show_empty_state_ui()
                 return

        render_payload(data)
            
    except Exception as e:
        show_empty_state_ui()


def render_dynamic_analysis(payload: Dict):
    st.title(payload.get("title", "Análisis"))
    # Usar render_payload para coherencia
    render_payload(payload)
    if st.button("Volver al Resumen"):
        st.session_state["current_view"] = None
        st.rerun()


def render_chat_sidebar():
    st.sidebar.title("💬 Chat AFI")
    # Mostrar historial
    for msg in st.session_state["messages"]:
        role = msg.get("role")
        content = msg.get("content")
        payload = msg.get("payload")
        
        with st.sidebar.chat_message(role):
            if role == "assistant":
                if payload:
                    render_payload(payload)
                else:
                    st.markdown(content)
            else:
                st.markdown(content)

    user_input = st.sidebar.chat_input("Analiza mis finanzas...")
    if user_input:
        st.session_state["messages"].append({"role": "user", "content": user_input})
        try:
            response = call_core_api(user_input)
            st.session_state["messages"].append(
                {"role": "assistant", "content": response.get("answer", ""), "payload": response}
            )
            st.session_state["current_view"] = response
        except Exception as e:
            st.sidebar.error(f"Error: {e}")
        st.rerun()


def main():
    if st.session_state.get("auth_stage") != "ready" or not st.session_state.get("auth_token"):
        show_login_screen()
        return

    render_chat_sidebar()

    if not st.session_state.get("current_view"):
        render_executive_summary()
    else:
        render_dynamic_analysis(st.session_state["current_view"])


if __name__ == "__main__":
    main()