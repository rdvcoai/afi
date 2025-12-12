# AFI - Asesor Financiero Inteligente

## Project Overview

**AFI** (Asesor Financiero Inteligente) is an autonomous, private Single-Family Office system powered by contextual AI. It is designed to act as a "God Mode" financial assistant, integrating various services to manage finances, audit communications, and provide intelligent insights via a WhatsApp interface.

### Key Capabilities
*   **Financial Vault:** Self-hosted **Actual Budget** for transaction tracking and budgeting.
*   **Contextual Brain:** Python-based core (`afi-core`) utilizing **Gemini** (Google) and **Ollama** (local LLMs) for reasoning.
*   **Vector Memory:** **ChromaDB** for RAG (Retrieval-Augmented Generation) to store and recall financial context and documents (books, etc.).
*   **Secure Interface:** **WhatsApp** integration (`afi-whatsapp`) serves as the primary user interface.
*   **Automated Auditing:** Intelligent scanning of emails (`imap-tools`) to detect assets, liabilities, and recurring expenses.

## Architecture

The project is a containerized microservices architecture managed via `docker-compose.yml`:

| Service | Container Name | Port | Description |
| :--- | :--- | :--- | :--- |
| **afi-core** | `afi_core` | `8080` | The Python "Brain". Runs FastAPI/Uvicorn. Handles logic, RAG, and email auditing. |
| **afi-whatsapp** | `afi_whatsapp` | `3000` | Node.js service acting as the bridge to WhatsApp. |
| **actual-server** | `afi_actual` | `5006` | Actual Budget instance (Financial Vault). |
| **chroma-db** | - | `8000` | Vector database for memory. |
| **ollama-local** | `afi_ollama` | - | Local LLM inference server (e.g., Qwen). |
| **postgres** | `afi_db` | - | PostgreSQL database with `pgvector` support. |
| **nginx** | `afi_nginx` | `80/443`| Reverse proxy and SSL termination. |

## Building and Running

### Prerequisites
*   Docker & Docker Compose
*   Gemini API Key
*   Google App Password (for Gmail auditing)

### Setup
1.  **Environment Variables:**
    Copy `.env.example` to `.env` and populate it:
    ```bash
    cp .env.example .env
    # Edit .env with GOOGLE_API_KEY, EMAIL_USER, EMAIL_PASS, etc.
    ```

2.  **Start Services:**
    ```bash
    docker-compose up --build -d
    ```

3.  **Access Points:**
    *   **Actual Budget:** `http://localhost:5006`
    *   **AFI Brain:** `http://localhost:8080`

## Key Workflows

### Financial Audit (Email Analysis)
The system can audit emails to discover financial information.
*   **Script:** `afi-core/full_audit.py`
*   **Execution:**
    ```bash
    # Run an audit for the last 365 days
    docker-compose run --rm -e AUDIT_DAYS=365 afi-core python /app/full_audit.py
    ```
*   **Output:** JSON reports in `data/` (e.g., `auditoria_YYYYMMDD.json`).

## Development Conventions

### Tech Stack
*   **Backend:** Python 3.12+ (FastAPI, LangChain, Pandas, Numpy).
*   **Frontend/Interface:** Node.js (WhatsApp Bridge).
*   **Database:** PostgreSQL, ChromaDB.
*   **AI/ML:** Google Gemini (via `google-generativeai`), Ollama (local inference).

### Data Management
*   **Persistence:** All persistent data is stored in the `./data/` directory (mounted volumes).
*   **Configuration:** Secrets and config via `.env`.

### Testing
*   Tests are located in `afi-core/tests/`.
*   Run tests (inside the container):
    ```bash
    pytest
    ```

## Documentation
*   `README.md`: General project info.
*   `INSTRUCCIONES_AUDITORIA.md`: Detailed manual for the email audit process.
