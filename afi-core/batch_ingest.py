import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import google.generativeai as genai
from dotenv import load_dotenv

from db_ops import ensure_account, insert_transactions, list_accounts


PROMPT = (
    "Analiza este documento completo. Extrae el 100% de las transacciones. "
    "Moneda: COP. Ignora saldos. Formato salida: JSON Array con campos date, amount, payee_name, notes."
)
ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def load_env() -> None:
    try:
        load_dotenv()
    except Exception:
        pass


def configure_genai() -> None:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ Falta GOOGLE_API_KEY en el entorno. Abortando.")
        sys.exit(1)
    genai.configure(api_key=api_key)


def get_base_dir() -> Path:
    return Path(os.getenv("ONEDRIVE_IMPORT_DIR", "/app/data/onedrive_import"))


def get_model_name() -> str:
    return os.getenv("GEMINI_BATCH_MODEL", "gemini-2.5-pro")


def scan_files(base_dir: Path) -> List[Path]:
    if not base_dir.exists():
        print(f"⚠️ Directorio no encontrado: {base_dir}")
        return []
    files: List[Path] = []
    for root, _dirs, filenames in os.walk(base_dir):
        for name in filenames:
            if name.startswith(".") or name.lower() in {"desktop.ini", "thumbs.db"}:
                continue
            files.append(Path(root) / name)
    return files


def collect_account_documents(base_dir: Path) -> List[Tuple[str, Path]]:
    """
    Cada subcarpeta es una cuenta. Ignora carpeta 'csv' y archivos en la raíz.
    Solo procesa PDFs/imagenes permitidas.
    """
    tasks: List[Tuple[str, Path]] = []
    if not base_dir.exists():
        print(f"⚠️ Directorio no encontrado: {base_dir}")
        return tasks

    for entry in base_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name.lower() == "csv":
                continue
            for doc in entry.rglob("*"):
                if not doc.is_file():
                    continue
                if doc.name.startswith("."):
                    continue
                if doc.suffix.lower() not in ALLOWED_EXTS:
                    continue
                tasks.append((entry.name, doc))
        # Si hay archivos en raíz, los ignoramos para respetar la regla de carpeta=cuenta.
    return tasks


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def parse_gemini_response(text: str) -> List[Dict]:
    clean = text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(clean)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception as e:
        print(f"⚠️ No se pudo parsear JSON devuelto por Gemini: {e}")
    return []


def extract_transactions(file_path: Path, mime_type: str, model_name: str) -> List[Dict]:
    print(f"🤖 Enviando a Gemini: {file_path} ({mime_type})")
    uploaded = genai.upload_file(path=str(file_path), mime_type=mime_type)
    while uploaded.state.name == "PROCESSING":
        time.sleep(1)
        uploaded = genai.get_file(uploaded.name)

    model = genai.GenerativeModel(model_name)
    response = model.generate_content([PROMPT, uploaded])
    text = response.text or ""
    return parse_gemini_response(text)


def normalize_transactions(raw_txs: List[Dict], source: str) -> List[Dict]:
    normalized: List[Dict] = []
    for tx in raw_txs:
        amount_val = tx.get("amount") if isinstance(tx, dict) else None
        date_val = tx.get("date") if isinstance(tx, dict) else None
        payee_val = ""
        notes_val = ""
        if isinstance(tx, dict):
            payee_val = tx.get("payee_name") or tx.get("payee") or tx.get("descripcion") or "Sin payee"
            notes_val = tx.get("notes") or tx.get("memo") or ""
        if amount_val is None or not date_val:
            continue
        try:
            amount_float = float(amount_val)
        except Exception:
            continue
        if amount_float == 0:
            continue
        normalized.append(
            {
                "date": str(date_val),
                "amount": amount_float,
                "payee_name": str(payee_val)[:120],
                "notes": str(notes_val or f"Fuente: {source}")[:200],
            }
        )
    return normalized


def import_transactions(account_id: int, account_name: str, txs: List[Dict], source: str) -> int:
    mapped = []
    for tx in txs:
        mapped.append(
            {
                "date": tx.get("date"),
                "amount": tx.get("amount"),
                "description": tx.get("payee_name") or tx.get("description") or account_name,
                "category": tx.get("category"),
                "import_source": source,
            }
        )
    return insert_transactions(account_id, mapped, import_source=source)


def main():
    load_env()
    configure_genai()

    base_dir = get_base_dir()
    model_name = get_model_name()

    tasks = collect_account_documents(base_dir)
    if not tasks:
        print(f"⚠️ No se encontraron documentos válidos en subcarpetas de {base_dir}.")
        return

    print(f"📂 Detectados {len(tasks)} archivos (PDF/imagen) para ingesta.")
    existing_accounts = {name.lower() for _id, name in list_accounts()}
    report = []

    for account_name, path in tasks:
        mime_type = guess_mime(path)
        try:
            account_id = ensure_account(account_name)
            created = account_name.lower() not in existing_accounts
            existing_accounts.add(account_name.lower())
            status_account = "creada" if created else "existente"
            print(f"🏦 Cuenta objetivo: {account_name} ({status_account}) -> {account_id}")

            raw_txs = extract_transactions(path, mime_type, model_name)
            normalized = normalize_transactions(raw_txs, source=path.name)
            if not normalized:
                print(f"⚠️ Ninguna transacción detectada en {path.name}")
                report.append((path.name, account_name, 0, "sin transacciones"))
                continue

            inserted = import_transactions(account_id, account_name, normalized, source=path.name)
            tx_count = len(normalized)
            print(f"✅ {tx_count} movimientos importados desde {path.name}")
            report.append((path.name, account_name, tx_count, f"ok ({inserted})"))
        except Exception as e:
            print(f"❌ Error procesando {path.name}: {e}")
            report.append((path.name, account_name, 0, f"error: {e}"))

    print("\n📑 Resumen de ingesta:")
    for filename, acct, count, status in report:
        print(f" - {filename} -> {acct} -> {count} movimientos -> {status}")


if __name__ == "__main__":
    main()
