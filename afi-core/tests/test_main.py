import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Asegurar que el path incluya la app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Stubs para módulos externos pesados antes de importar main
class _DummyFastAPI:
    def __init__(self, *_, **__):
        pass

    def get(self, *_, **__):
        def decorator(func):
            return func

        return decorator

    def on_event(self, *_, **__):
        def decorator(func):
            return func

        return decorator

    def post(self, *_, **__):
        def decorator(func):
            return func

        return decorator


class _DummyBaseModel:
    pass


class _DummyAsyncIOScheduler:
    def __init__(self, *_, **__):
        pass

    def add_job(self, *_, **__):
        pass

    def start(self, *_, **__):
        pass


class _DummyCronTrigger:
    def __init__(self, *_, **__):
        pass


sys.modules.setdefault("fastapi", types.SimpleNamespace(FastAPI=_DummyFastAPI, Request=MagicMock()))
sys.modules.setdefault("pydantic", types.SimpleNamespace(BaseModel=_DummyBaseModel))

_google_mod = types.ModuleType("google")
_genai_mod = MagicMock()
sys.modules["google"] = _google_mod
sys.modules["google.generativeai"] = _genai_mod
setattr(_google_mod, "generativeai", _genai_mod)
sys.modules.setdefault(
    "apscheduler.schedulers.asyncio", types.SimpleNamespace(AsyncIOScheduler=_DummyAsyncIOScheduler)
)
sys.modules.setdefault("apscheduler.triggers.cron", types.SimpleNamespace(CronTrigger=_DummyCronTrigger))
sys.modules.setdefault("httpx", MagicMock())
sys.modules.setdefault("email_ingest", MagicMock(process_emails=MagicMock()))
sys.modules.setdefault("identity_manager", MagicMock(get_user_session=MagicMock(return_value={"id": 1})))
sys.modules.setdefault(
    "tools",
    types.SimpleNamespace(
        TOOLS_SCHEMA=[],
        get_financial_audit=lambda: None,
        create_category_tool=lambda *_, **__: None,
        categorize_payees_tool=lambda *_, **__: None,
    ),
)

# Mock de la conexión a DB para evitar Postgres real durante la importación de main
with patch("database.get_conn") as _mock_get_conn:
    _mock_conn = MagicMock()
    _mock_cursor = MagicMock()
    _mock_get_conn.return_value = _mock_conn
    _mock_conn.__enter__.return_value = _mock_conn
    _mock_conn.cursor.return_value.__enter__.return_value = _mock_cursor
    import main

# Datos de prueba
TEST_PHONE = "573001234567"
USER_CTX = {"phone": TEST_PHONE}
MOCK_CSV_DATA = '{"total_spent":100,"summary":"Gastos: Uber $500, D1 $200"}'


@pytest.fixture
def mock_dependencies():
    """Mockea dependencias externas del router."""
    with patch("main.get_user_context") as mock_get_ctx, patch(
        "main.save_user_context"
    ) as mock_save_ctx, patch("main.get_financial_audit") as mock_audit, patch(
        "main.genai.GenerativeModel"
    ) as mock_model_cls, patch(
        "main.init_db"
    ) as mock_init, patch("main.genai.embed_content") as mock_embed:
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Respuesta de IA"
        mock_response.parts = []  # evita loop de tool-calls
        mock_chat.send_message.return_value = mock_response

        mock_model_instance = MagicMock()
        mock_model_instance.start_chat.return_value = mock_chat
        mock_model_cls.return_value = mock_model_instance
        mock_embed.return_value = {"embedding": [0.1, 0.2, 0.3]}

        yield {
            "get_ctx": mock_get_ctx,
            "save_ctx": mock_save_ctx,
            "audit": mock_audit,
            "model_cls": mock_model_cls,
            "chat": mock_chat,
            "embed": mock_embed,
        }


def test_cold_start_with_csv(mock_dependencies):
    """
    Caso: Usuario nuevo (DB vacía) pero con archivo CSV presente.
    Debe: Leer CSV, Guardar en DB (Onboarding) e Inyectar contexto en Prompt.
    """
    mocks = mock_dependencies
    mocks["get_ctx"].return_value = None
    mocks["audit"].return_value = MOCK_CSV_DATA

    response = main.ai_router("Hola", USER_CTX)

    assert response == "Respuesta de IA"
    mocks["audit"].assert_called_once()
    mocks["save_ctx"].assert_called_once_with(TEST_PHONE, file_summary=MOCK_CSV_DATA, mode="ONBOARDING")

    call_args = mocks["model_cls"].call_args
    system_instruction = call_args[1]["system_instruction"]
    assert MOCK_CSV_DATA in system_instruction
    assert "ESTADO ACTUAL: ONBOARDING" in system_instruction


def test_warm_start_memory_hit(mock_dependencies):
    """
    Caso: Usuario existente (DB tiene datos).
    Debe: Leer de DB (NO leer CSV físico) y usar ese contexto.
    """
    mocks = mock_dependencies
    mocks["get_ctx"].return_value = {"file_context": "Memoria Persistente", "mode": "NORMAL"}

    main.ai_router("Hola", USER_CTX)

    mocks["audit"].assert_not_called()
    mocks["save_ctx"].assert_not_called()
    call_args = mocks["model_cls"].call_args
    system_instruction = call_args[1]["system_instruction"]
    assert "Memoria Persistente" in system_instruction
    assert "ESTADO ACTUAL: NORMAL" in system_instruction


def test_empty_state_no_csv(mock_dependencies):
    """
    Caso: Usuario nuevo y SIN archivo CSV.
    Debe: Iniciar en modo entrevista limpio (sin contexto basura).
    """
    mocks = mock_dependencies
    mocks["get_ctx"].return_value = None
    mocks["audit"].side_effect = Exception("No file")

    main.ai_router("Hola", USER_CTX)

    call_args = mocks["model_cls"].call_args
    system_instruction = call_args[1]["system_instruction"]
    assert "MEMORIA DEL USUARIO" in system_instruction
    mocks["save_ctx"].assert_not_called()
