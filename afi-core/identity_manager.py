import os

# Configuración de Perfiles
USERS = {
    os.getenv("ADMIN_PHONE"): {
        "name": "Diego",
        "role": "ADMIN",
        "personal_id": os.getenv("ACTUAL_BUDGET_ID_MAIN") or os.getenv("ACTUAL_BUDGET_ID"),
        "household_id": os.getenv("ACTUAL_BUDGET_ID_HOUSEHOLD"),
        "persona": "CFO Estratégico",
    },
    os.getenv("SPOUSE_PHONE"): {
        "name": "Esposa",
        "role": "PARTNER",
        "personal_id": os.getenv("ACTUAL_BUDGET_ID_SPOUSE"),
        "household_id": os.getenv("ACTUAL_BUDGET_ID_HOUSEHOLD"),
        "persona": "Coach Empático",
    },
}


def get_user_session(phone_raw: str):
    """Normaliza número y devuelve la sesión de usuario configurada."""
    # Dejar solo dígitos para soportar variaciones (@c.us, @lid, +57, etc.)
    phone = "".join(ch for ch in phone_raw if ch.isdigit())
    if phone in USERS:
        return USERS[phone]

    # Coincidencia flexible por últimos 10 dígitos
    for k, v in USERS.items():
        if not k:
            continue
        if phone.endswith(k[-10:]) or k.endswith(phone[-10:]):
            return v

    # Fallback: devolver el primer perfil definido (evita bloqueo si WA entrega IDs raros)
    for v in USERS.values():
        if v:
            return v
    return None
