"""Rerank retrieval results using a Cross-Encoder for higher precision."""

from sentence_transformers import CrossEncoder

class RAGReranker:
    """
    Reranks a list of candidate documents based on their semantic relevance 
    to a query using a Cross-Encoder model.
    """
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, documents: list[str], top_k: int = 5) -> list[int]:
        """
        Returns the indices of the top-k documents sorted by relevance.
        """
        if not documents:
            return []
        
        # Prepare pairs for the cross-encoder: [[query, doc1], [query, doc2], ...]
        pairs = [[query, doc] for doc in documents]
        scores = self.model.predict(pairs)
        
        # Sort indices by score in descending order
        sorted_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return sorted_indices[:top_k]
