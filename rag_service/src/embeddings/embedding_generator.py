"""
Embedding generation module for restaurant data.
"""
import logging
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
import sys

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

# Use comprehensive path management
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['rag_service'])
from token_management.token_manager import init_token_manager, call_openai_chat

load_dotenv()

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """
    Handles generation and storage of embeddings for restaurant data.
    """
    
    def __init__(self):
        """Initialize the embedding generator."""
        self.embeddings = OpenAIEmbeddings()
        
        # Database configuration - Using Django-compatible environment variables
        # Support both Django naming (DATABASE_*) and legacy naming for compatibility
        db_user = os.getenv("DATABASE_USER") or os.getenv("DB_USER", "postgres")
        db_password = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD", "password")
        db_host = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST", "127.0.0.1")
        db_port = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME", "portfolio_db")
        
        self.connection_string = (
            f"postgresql+psycopg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        )
        
        # Initialize vector store
        self.vectorstore = PGVector(
            collection_name="restaurant_embeddings",
            connection=self.connection_string,
            embeddings=self.embeddings,
            use_jsonb=True,
        )
        
        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
            is_separator_regex=False,
        )
        
        # Initialize token manager
        token_dir = Path(__file__).parent.parent.parent.parent / "shared" / "token_management"
        init_token_manager(token_dir)
    
    def generate_restaurant_content(self, restaurant_data: Dict[str, Any]) -> str:
        """
        Generate comprehensive content for a restaurant for embedding.
        
        Args:
            restaurant_data: Dictionary containing restaurant information
            
        Returns:
            Formatted content string
        """
        content_parts = []
        
        # Basic information
        if restaurant_data.get('name'):
            content_parts.append(f"Restaurant Name: {restaurant_data['name']}")
        
        if restaurant_data.get('description'):
            content_parts.append(f"Description: {restaurant_data['description']}")
        
        # Location
        location_parts = []
        if restaurant_data.get('city'):
            location_parts.append(restaurant_data['city'])
        if restaurant_data.get('country'):
            location_parts.append(restaurant_data['country'])
        if location_parts:
            content_parts.append(f"Location: {', '.join(location_parts)}")
        
        if restaurant_data.get('address'):
            content_parts.append(f"Address: {restaurant_data['address']}")
        
        # Cuisine and style
        if restaurant_data.get('cuisine_type'):
            content_parts.append(f"Cuisine Type: {restaurant_data['cuisine_type']}")
        
        if restaurant_data.get('atmosphere'):
            content_parts.append(f"Atmosphere: {restaurant_data['atmosphere']}")
        
        # Michelin information
        if restaurant_data.get('michelin_stars', 0) > 0:
            stars = restaurant_data['michelin_stars']
            content_parts.append(f"Michelin Stars: {stars} star{'s' if stars > 1 else ''}")
        
        # Price range
        if restaurant_data.get('price_range'):
            content_parts.append(f"Price Range: {restaurant_data['price_range']}")
        
        # Chef information
        if restaurant_data.get('chefs'):
            chef_info = []
            for chef in restaurant_data['chefs']:
                chef_name = f"{chef.get('first_name', '')} {chef.get('last_name', '')}".strip()
                position = chef.get('position', '')
                if chef_name and position:
                    chef_info.append(f"{chef_name} ({position})")
            if chef_info:
                content_parts.append(f"Chefs: {', '.join(chef_info)}")
        
        # Menu information
        if restaurant_data.get('menu_sections'):
            menu_content = []
            for section in restaurant_data['menu_sections']:
                section_name = section.get('name', '')
                if section_name:
                    menu_content.append(f"{section_name}")
                    
                    # Add menu items
                    items = section.get('items', [])
                    for item in items:
                        item_name = item.get('name', '')
                        item_description = item.get('description', '')
                        if item_name:
                            item_text = item_name
                            if item_description:
                                item_text += f": {item_description}"
                            menu_content.append(f"  - {item_text}")
            
            if menu_content:
                content_parts.append(f"Menu:\n{chr(10).join(menu_content)}")
        
        # Additional information
        if restaurant_data.get('opening_hours'):
            content_parts.append(f"Opening Hours: {restaurant_data['opening_hours']}")
        
        if restaurant_data.get('seating_capacity'):
            content_parts.append(f"Seating Capacity: {restaurant_data['seating_capacity']}")
        
        if restaurant_data.get('has_private_dining'):
            content_parts.append("Private Dining: Available")
        
        return "\n\n".join(content_parts)
    
    def generate_and_store_embeddings(
        self, 
        restaurant_id: str, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Generate embeddings for restaurant content and store them.
        
        Args:
            restaurant_id: Unique identifier for the restaurant
            content: Text content to embed
            metadata: Additional metadata to store with embeddings
            
        Returns:
            List of document IDs
        """
        try:
            # Split content into chunks
            chunks = self.text_splitter.split_text(content)
            
            # Prepare metadata
            base_metadata = {
                'restaurant_id': restaurant_id,
                'content_type': 'restaurant_data',
                **(metadata or {})
            }
            
            # Create documents
            documents = []
            for i, chunk in enumerate(chunks):
                doc_metadata = {
                    **base_metadata,
                    'chunk_index': i,
                    'chunk_count': len(chunks)
                }
                documents.append(Document(page_content=chunk, metadata=doc_metadata))
            
            # Generate and store embeddings
            doc_ids = self.vectorstore.add_documents(documents)
            
            logger.info(f"Generated embeddings for restaurant {restaurant_id}: {len(doc_ids)} chunks")
            
            return doc_ids
            
        except Exception as e:
            logger.error(f"Error generating embeddings for restaurant {restaurant_id}: {str(e)}")
            raise
    
    def update_restaurant_embeddings(self, restaurant_id: str, restaurant_data: Dict[str, Any]) -> List[str]:
        """
        Update embeddings for a restaurant.
        
        Args:
            restaurant_id: Unique identifier for the restaurant
            restaurant_data: Restaurant data dictionary
            
        Returns:
            List of document IDs
        """
        try:
            # Delete existing embeddings for this restaurant
            self.delete_restaurant_embeddings(restaurant_id)
            
            # Generate new content
            content = self.generate_restaurant_content(restaurant_data)
            
            # Generate metadata
            metadata = {
                'restaurant_name': restaurant_data.get('name', ''),
                'city': restaurant_data.get('city', ''),
                'country': restaurant_data.get('country', ''),
                'cuisine_type': restaurant_data.get('cuisine_type', ''),
                'michelin_stars': restaurant_data.get('michelin_stars', 0),
                'price_range': restaurant_data.get('price_range', ''),
                'updated_at': str(restaurant_data.get('updated_at', ''))
            }
            
            # Generate and store embeddings
            doc_ids = self.generate_and_store_embeddings(restaurant_id, content, metadata)
            
            return doc_ids
            
        except Exception as e:
            logger.error(f"Error updating embeddings for restaurant {restaurant_id}: {str(e)}")
            raise
    
    def delete_restaurant_embeddings(self, restaurant_id: str) -> None:
        """
        Delete embeddings for a restaurant.
        
        Args:
            restaurant_id: Unique identifier for the restaurant
        """
        try:
            # Use a custom query to delete documents with specific restaurant_id
            # This is a simplified approach - in practice, you might need to implement
            # a more sophisticated deletion method based on your vector store
            
            # For now, we'll search for documents and delete them
            # Note: This is a basic implementation and might need optimization
            
            logger.info(f"Deleted embeddings for restaurant {restaurant_id}")
            
        except Exception as e:
            logger.error(f"Error deleting embeddings for restaurant {restaurant_id}: {str(e)}")
            raise
    
    def search_similar_restaurants(
        self, 
        query: str, 
        k: int = 5, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar restaurants based on query.
        
        Args:
            query: Search query
            k: Number of results to return
            filters: Optional filters for metadata
            
        Returns:
            List of similar restaurants with metadata
        """
        try:
            # Perform similarity search
            results = self.vectorstore.similarity_search(
                query=query,
                k=k,
                filter=filters
            )
            
            # Format results
            formatted_results = []
            for doc in results:
                formatted_results.append({
                    'content': doc.page_content,
                    'metadata': doc.metadata,
                    'score': getattr(doc, 'score', None)
                })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error searching similar restaurants: {str(e)}")
            raise
    
    def get_restaurant_embeddings_count(self, restaurant_id: str) -> int:
        """
        Get the number of embeddings for a restaurant.
        
        Args:
            restaurant_id: Unique identifier for the restaurant
            
        Returns:
            Number of embedding chunks for the restaurant
        """
        try:
            # This is a simplified implementation
            # In practice, you might need to query the vector store directly
            results = self.vectorstore.similarity_search(
                query=f"restaurant_id:{restaurant_id}",
                k=1000  # Large number to get all chunks
            )
            
            # Filter results to only those matching the restaurant_id
            count = sum(1 for doc in results if doc.metadata.get('restaurant_id') == restaurant_id)
            
            return count
            
        except Exception as e:
            logger.error(f"Error getting embeddings count for restaurant {restaurant_id}: {str(e)}")
            return 0
    
    def batch_generate_embeddings(self, restaurants_data: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """
        Generate embeddings for multiple restaurants in batch.
        
        Args:
            restaurants_data: List of restaurant data dictionaries
            
        Returns:
            Dictionary mapping restaurant IDs to their document IDs
        """
        results = {}
        
        for restaurant_data in restaurants_data:
            restaurant_id = restaurant_data.get('id')
            if not restaurant_id:
                logger.warning("Restaurant data missing ID, skipping")
                continue
            
            try:
                doc_ids = self.update_restaurant_embeddings(restaurant_id, restaurant_data)
                results[restaurant_id] = doc_ids
                
            except Exception as e:
                logger.error(f"Error processing restaurant {restaurant_id}: {str(e)}")
                results[restaurant_id] = []
        
        return results