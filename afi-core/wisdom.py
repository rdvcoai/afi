import chromadb


class WisdomRetriever:
    def __init__(self):
        self.client = chromadb.HttpClient(host="chroma-db", port=8000)
        self.collection = self.client.get_collection("financial_wisdom")

    def get_advice(self, query: str, n_results: int = 3):
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        context = "\n".join(results["documents"][0]) if results["documents"] else ""
        sources = [m.get("source") for m in results["metadatas"][0]] if results["metadatas"] else []
        return context, sources
