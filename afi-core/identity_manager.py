import os

# Whitelist de usuarios autorizados
AUTHORIZED_PHONES = {
    "3002127123": {
        "name": "Diego (Tel)",
        "role": "ADMIN",
        "personal_id": os.getenv("ACTUAL_BUDGET_ID_MAIN"),
        "household_id": os.getenv("ACTUAL_BUDGET_ID_HOUSEHOLD"),
        "persona": "CFO Estratégico",
    },
    "20590190669871": {  # ID detectado en logs para Diego
        "name": "Diego (LID)",
        "role": "ADMIN",
        "personal_id": os.getenv("ACTUAL_BUDGET_ID_MAIN"),
        "household_id": os.getenv("ACTUAL_BUDGET_ID_HOUSEHOLD"),
        "persona": "CFO Estratégico",
    },
    "3113570340": {
        "name": "Usuario2",
        "role": "USER",
        "personal_id": os.getenv("ACTUAL_BUDGET_ID_SPOUSE"),
        "household_id": os.getenv("ACTUAL_BUDGET_ID_HOUSEHOLD"),
        "persona": "Coach Empático",
    },
}


def normalize_identity(phone_raw: str) -> str:
    """
    Normaliza la identidad entrante (E.164 simplificado).
    1. Elimina todo lo que no sea dígito.
    2. Si es longitud 12 y empieza por 573... (Colombia), quita el 57.
    """
    clean = "".join(ch for ch in phone_raw if ch.isdigit())
    
    # Regla Colombia: 57 + 3XX... (10 dígitos) = 12 dígitos
    if len(clean) == 12 and clean.startswith("573"):
        return clean[2:]
        
    return clean

def get_user_session(phone_raw: str):
    """Normaliza número y devuelve la sesión de usuario configurada si está autorizado."""
    phone = normalize_identity(phone_raw)
    
    # Match Exacto
    if phone in AUTHORIZED_PHONES:
        return AUTHORIZED_PHONES[phone]
    
    # Match Flexible (endswith)
    for auth_phone, user_data in AUTHORIZED_PHONES.items():
        if phone.endswith(auth_phone) or auth_phone.endswith(phone):
            return user_data

    return None
