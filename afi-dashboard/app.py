import os
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
            st.error(f"🔥 Error del Núcleo ({r.status_code}): {r.text}")
            return {"answer": f"Error del sistema: {r.status_code}", "viz_type": "text"}
    except Exception as e:
        st.error(f"❌ Error de Conexión: {str(e)}")
        return {"answer": "No se pudo conectar con el cerebro de AFI.", "viz_type": "text"}


# --- Render helpers ---
def render_payload(data):
    """
    Renderiza la respuesta de AFI de forma limpia.
    Maneja texto puro (Onboarding) y gráficos (Dashboard).
    """
    # 1. EVITAR JSON CRUDO
    # Si data viene como string JSON, convertirlo a dict
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            st.error("Error parseando respuesta del servidor")
            return

    # 2. EXTRAER EL TEXTO (La respuesta hablada)
    # Si existe 'answer', muéstralo como Markdown limpio, NO como dict
    answer_text = data.get("answer", "")
    if answer_text:
        # Usamos un contenedor limpio, sin bordes de código
        st.markdown(f"### 🤖 AFI dice:\n{answer_text}")

    # 3. RENDERIZAR VISUALES (Si existen)
    viz_type = data.get("viz_type")
    
    # Caso especial: Onboarding (Solo texto)
    if viz_type == "text":
        return # Ya pintamos el texto arriba, no hacemos nada más

    # Caso Dashboard: Gráficos
    raw_data = data.get("data", [])
    if raw_data:
        df = pd.DataFrame(raw_data)
        
        if viz_type == "bar_chart":
            fig = px.bar(df, x=df.columns[0], y=df.columns[1], title=data.get("title"))
            st.plotly_chart(fig, use_container_width=True)
            
        elif viz_type == "line_chart":
            fig = px.line(df, x=df.columns[0], y=df.columns[1], title=data.get("title"))
            st.plotly_chart(fig, use_container_width=True)
            
        elif viz_type == "table":
            st.dataframe(df, use_container_width=True)
            
        elif viz_type == "metric":
            val = df.iloc[0, 1] if not df.empty else 0
            st.metric(label=data.get("title"), value=f"${val:,.0f}")


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
    summary = call_core_api("Dame un resumen ejecutivo con patrimonio total, gastos del mes, deuda y tendencia mensual.")
    
    render_payload(summary)


def render_dynamic_analysis(payload: Dict):
    st.title(payload.get("title", "Análisis"))
    st.markdown(payload.get("answer") or payload.get("explanation") or "")
    render_payload(payload)
    if st.button("Volver al Resumen"):
        st.session_state["current_view"] = None
        st.rerun()


def render_chat_sidebar():
    st.sidebar.title("💬 Chat AFI")
    # Mostrar historial
    for msg in st.session_state["messages"]:
        if msg.get("content"):
            with st.sidebar.expander(f"{msg['role'].capitalize()}: {msg['content'][:30]}..."):
                st.write(msg["content"])
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
