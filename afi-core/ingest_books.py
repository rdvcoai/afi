import os
import chromadb
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Rutas dentro del contenedor
BOOKS_PATH = "/app/books"
CHROMA_HOST = "chroma-db" # Nombre del servicio docker
CHROMA_PORT = 8000

def ingest_library():
    print("📚 AFI: Iniciando Ingestión de Biblioteca Financiera...")

    # Cliente HTTP para hablar con el contenedor de Chroma
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

    # Crear colección "sabiduría"
    collection = client.get_or_create_collection(name="financial_wisdom")

    # Buscar PDFs
    if not os.path.exists(BOOKS_PATH):
        print(f"❌ Error: No existe {BOOKS_PATH}")
        return

    pdf_files = [f for f in os.listdir(BOOKS_PATH) if f.endswith('.pdf')]
    print(f"🔍 Encontrados {len(pdf_files)} libros.")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )

    for pdf_file in pdf_files:
        print(f"📖 Procesando: {pdf_file}...")
        try:
            loader = PyPDFLoader(os.path.join(BOOKS_PATH, pdf_file))
            docs = loader.load_and_split(text_splitter)

            # Preparar datos
            ids = [f"{pdf_file}_{i}" for i in range(len(docs))]
            documents = [d.page_content for d in docs]
            metadatas = [{"source": pdf_file, "page": d.metadata.get('page', 0)} for d in docs]

            # Insertar en lotes (Chroma maneja batching, pero esto es seguro)
            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            print(f"✅ {pdf_file}: {len(docs)} fragmentos guardados.")
        except Exception as e:
            print(f"⚠️ Error leyendo {pdf_file}: {e}")

    print("🏁 Ingestión Completa. AFI ahora es sabio.")

if __name__ == "__main__":
    ingest_library()
