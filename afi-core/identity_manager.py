import os

# Whitelist de usuarios autorizados
AUTHORIZED_PHONES = {
    "3002127123": {
        "name": "Usuario1",
        "role": "ADMIN",  # Asumiendo que el primero es el administrador principal
        "personal_id": os.getenv("ACTUAL_BUDGET_ID_MAIN"),
        "household_id": os.getenv("ACTUAL_BUDGET_ID_HOUSEHOLD"),
        "persona": "CFO Estratégico",
    },
    "3113570340": {
        "name": "Usuario2",
        "role": "USER",
        "personal_id": os.getenv("ACTUAL_BUDGET_ID_SPOUSE"), # Opcional, si corresponde
        "household_id": os.getenv("ACTUAL_BUDGET_ID_HOUSEHOLD"),
        "persona": "Coach Empático",
    },
}


def get_user_session(phone_raw: str):
    """Normaliza número y devuelve la sesión de usuario configurada si está autorizado."""
    # Dejar solo dígitos para soportar variaciones (@c.us, @lid, +57, etc.)
    phone = "".join(ch for ch in phone_raw if ch.isdigit())
    
    # Check if the normalized phone number is in the whitelist
    if phone in AUTHORIZED_PHONES:
        return AUTHORIZED_PHONES[phone]
    
    # Fallback for partial matches (e.g., if a number comes in as 57300... or 300...)
    # This assumes the whitelist numbers are full international format or expected local format
    for auth_phone, user_data in AUTHORIZED_PHONES.items():
        if phone.endswith(auth_phone) or auth_phone.endswith(phone):
            return user_data

    return None
