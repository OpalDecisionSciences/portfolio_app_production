#!/usr/bin/env python3
"""
Test script for hybrid retrieval system.
"""
import sys
from pathlib import Path

# Use comprehensive path management
sys.path.insert(0, str(Path(__file__).parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['rag_service'])

from retrieval.hybrid_retriever import HybridRetriever
from langchain_core.documents import Document

def test_bm25_standalone():
    """Test BM25 functionality without OpenAI dependencies."""
    print("Testing BM25 standalone functionality...")
    
    # Create mock documents
    docs = [
        Document(
            page_content="Le Bernardin is a French seafood restaurant in New York City. Chef Eric Ripert serves exquisite fish dishes with Michelin three stars.",
            metadata={"restaurant_name": "Le Bernardin", "city": "New York", "cuisine": "French", "michelin_stars": 3}
        ),
        Document(
            page_content="Osteria Francescana in Modena Italy serves traditional Italian cuisine. Chef Massimo Bottura creates innovative pasta dishes.",
            metadata={"restaurant_name": "Osteria Francescana", "city": "Modena", "cuisine": "Italian", "michelin_stars": 3}
        ),
        Document(
            page_content="L'Ambroisie is a classic French restaurant in Paris. Located on Place des Vosges, it offers traditional French haute cuisine.",
            metadata={"restaurant_name": "L'Ambroisie", "city": "Paris", "cuisine": "French", "michelin_stars": 3}
        ),
        Document(
            page_content="Eleven Madison Park in New York serves plant-based fine dining. The restaurant focuses on seasonal vegetables and innovative techniques.",
            metadata={"restaurant_name": "Eleven Madison Park", "city": "New York", "cuisine": "Plant-based", "michelin_stars": 3}
        ),
        Document(
            page_content="Sushi Jiro in Tokyo serves traditional sushi. Master Jiro Ono prepares fresh fish with decades of experience in Japanese cuisine.",
            metadata={"restaurant_name": "Sushi Jiro", "city": "Tokyo", "cuisine": "Japanese", "michelin_stars": 3}
        )
    ]
    
    # Create a mock hybrid retriever (without vector store for BM25-only testing)
    class MockVectorStore:
        def similarity_search_with_score(self, query, k=5, filter=None):
            return []  # Return empty for BM25-only test
    
    try:
        # Initialize hybrid retriever with mock vector store
        hybrid_retriever = HybridRetriever(
            vector_store=MockVectorStore(),
            bm25_index_path="/tmp/test_bm25_index.pkl",
            alpha=0.0  # 100% sparse for this test
        )
        
        # Build BM25 index
        hybrid_retriever.build_bm25_index(docs)
        print(f"✓ Built BM25 index with {len(docs)} documents")
        
        # Test queries
        test_queries = [
            "French restaurant Paris",
            "sushi Tokyo Japan", 
            "Italian pasta",
            "New York seafood",
            "plant based vegetables"
        ]
        
        for query in test_queries:
            print(f"\nQuery: '{query}'")
            
            # Test BM25 search
            bm25_results = hybrid_retriever.bm25_search(query, k=3)
            print(f"BM25 Results ({len(bm25_results)}):")
            
            for i, (doc, score) in enumerate(bm25_results):
                restaurant_name = doc.metadata.get('restaurant_name', 'Unknown')
                city = doc.metadata.get('city', 'Unknown')
                print(f"  {i+1}. {restaurant_name} ({city}) - Score: {score:.3f}")
        
        # Test index stats
        stats = hybrid_retriever.get_index_stats()
        print(f"\nIndex Stats:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        print("\n✓ BM25 testing completed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Error in BM25 testing: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_bm25_standalone()
    sys.exit(0 if success else 1)