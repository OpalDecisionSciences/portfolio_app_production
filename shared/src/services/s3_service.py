"""
Centralized S3 Service for Portfolio Application
Handles all S3 operations for images, documents, and other media.

This service provides:
1. Unified S3 upload/download functionality
2. Image optimization before upload
3. Automatic retry logic
4. URL generation and management
5. Bulk operations support
"""

import os
import boto3
import hashlib
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError
from PIL import Image
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import json

# Configure logging
logger = logging.getLogger(__name__)


class S3Service:
    """
    Centralized S3 service for all AWS S3 operations.
    Singleton pattern to ensure single client instance.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(S3Service, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize S3 service with credentials and configuration."""
        if self._initialized:
            return
            
        # S3 Configuration from environment
        self.bucket_name = os.getenv('AWS_MEDIA_BUCKET_NAME', 'michelin-media-files')
        self.region = os.getenv('AWS_S3_REGION_NAME', 'us-east-1')
        self.access_key = os.getenv('AWS_ACCESS_KEY_ID')
        self.secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        
        # S3 path structure
        self.base_paths = {
            'restaurant_images': 'restaurant-images',
            'menu_images': 'menu-images',
            'chef_photos': 'chef-photos',
            'documents': 'documents',
            'scraped_content': 'scraped-content',
            'temp': 'temp'
        }
        
        # Image processing settings
        self.max_image_size = 2048  # Maximum width/height
        self.image_quality = 85  # JPEG quality
        self.supported_formats = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
        
        # Initialize S3 client
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region
            )
            
            # Test connection
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"S3 Service initialized with bucket: {self.bucket_name}")
            
        except NoCredentialsError:
            logger.error("AWS credentials not found. Check environment variables.")
            raise
        except ClientError as e:
            logger.error(f"Failed to connect to S3 bucket: {e}")
            raise
            
        self._initialized = True
    
    def generate_s3_key(self, 
                       content_type: str,
                       identifier: str,
                       filename: Optional[str] = None,
                       extension: str = '.jpg') -> str:
        """
        Generate a unique S3 key based on content type and identifier.
        
        Args:
            content_type: Type of content ('restaurant_images', 'menu_images', etc.)
            identifier: Unique identifier (restaurant name, ID, etc.)
            filename: Optional original filename
            extension: File extension
            
        Returns:
            S3 key path
        """
        base_path = self.base_paths.get(content_type, 'misc')
        
        # Clean identifier
        clean_id = "".join(c if c.isalnum() or c in (' ', '-', '_') else '' 
                          for c in identifier)
        clean_id = clean_id.replace(' ', '_').lower()[:50]
        
        # Generate timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Generate unique hash
        if filename:
            hash_input = f"{identifier}_{filename}_{timestamp}"
        else:
            hash_input = f"{identifier}_{timestamp}"
        
        unique_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        
        # Construct S3 key
        s3_key = f"{base_path}/{clean_id}/{timestamp}_{unique_hash}{extension}"
        
        return s3_key
    
    def optimize_image(self, image_data: bytes, max_size: Optional[int] = None) -> bytes:
        """
        Optimize image for web delivery.
        
        Args:
            image_data: Raw image data
            max_size: Maximum dimension (width/height)
            
        Returns:
            Optimized image data
        """
        try:
            img = Image.open(BytesIO(image_data))
            
            # Convert RGBA to RGB if needed
            if img.mode in ('RGBA', 'P', 'LA'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    rgb_img.paste(img, mask=img.split()[-1])
                else:
                    rgb_img.paste(img)
                img = rgb_img
            
            # Resize if too large
            max_dimension = max_size or self.max_image_size
            if img.width > max_dimension or img.height > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            
            # Save optimized image
            output = BytesIO()
            img.save(output, format='JPEG', quality=self.image_quality, optimize=True)
            return output.getvalue()
            
        except Exception as e:
            logger.error(f"Image optimization failed: {e}")
            return image_data  # Return original if optimization fails
    
    def upload_image(self,
                    image_data: bytes,
                    content_type: str,
                    identifier: str,
                    optimize: bool = True,
                    metadata: Optional[Dict] = None) -> Optional[Dict]:
        """
        Upload an image to S3 with optimization.
        
        Args:
            image_data: Image data to upload
            content_type: Type of content for path organization
            identifier: Unique identifier
            optimize: Whether to optimize image before upload
            metadata: Optional metadata to attach
            
        Returns:
            Dict with S3 URL, key, and metadata or None if failed
        """
        try:
            # Optimize image if requested
            if optimize:
                image_data = self.optimize_image(image_data)
            
            # Generate S3 key
            s3_key = self.generate_s3_key(content_type, identifier)
            
            # Prepare metadata
            s3_metadata = {
                'identifier': identifier,
                'upload_timestamp': datetime.now().isoformat(),
                'content_type': content_type
            }
            if metadata:
                s3_metadata.update(metadata)
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=image_data,
                ContentType='image/jpeg',
                ACL='public-read',
                Metadata={k: str(v) for k, v in s3_metadata.items()},
                CacheControl='max-age=86400'
            )
            
            # Generate public URL
            s3_url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{s3_key}"
            
            # Calculate hashes
            content_hash = hashlib.sha256(image_data).hexdigest()
            
            logger.info(f"Successfully uploaded image to S3: {s3_key}")
            
            return {
                's3_url': s3_url,
                's3_key': s3_key,
                'content_hash': content_hash,
                'file_size': len(image_data),
                'metadata': s3_metadata
            }
            
        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            return None
    
    def upload_from_url(self,
                       image_url: str,
                       content_type: str,
                       identifier: str,
                       optimize: bool = True) -> Optional[Dict]:
        """
        Download image from URL and upload to S3.
        
        Args:
            image_url: URL of image to download
            content_type: Type of content for path organization  
            identifier: Unique identifier
            optimize: Whether to optimize image
            
        Returns:
            Dict with S3 URL and metadata or None if failed
        """
        try:
            # Download image
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(image_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            image_data = response.content
            
            # Add source URL to metadata
            metadata = {
                'source_url': image_url,
                'source_url_hash': hashlib.sha256(image_url.encode()).hexdigest()
            }
            
            # Upload to S3
            return self.upload_image(
                image_data=image_data,
                content_type=content_type,
                identifier=identifier,
                optimize=optimize,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to upload from URL {image_url}: {e}")
            return None
    
    def upload_from_local(self,
                         local_path: str,
                         content_type: str,
                         identifier: str,
                         optimize: bool = True) -> Optional[Dict]:
        """
        Upload image from local file to S3.
        
        Args:
            local_path: Path to local image file
            content_type: Type of content for path organization
            identifier: Unique identifier
            optimize: Whether to optimize image
            
        Returns:
            Dict with S3 URL and metadata or None if failed
        """
        try:
            path = Path(local_path)
            if not path.exists():
                logger.error(f"Local file not found: {local_path}")
                return None
            
            image_data = path.read_bytes()
            
            # Add local path to metadata
            metadata = {
                'original_filename': path.name,
                'local_path': str(path)
            }
            
            # Upload to S3
            return self.upload_image(
                image_data=image_data,
                content_type=content_type,
                identifier=identifier,
                optimize=optimize,
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Failed to upload from local path {local_path}: {e}")
            return None
    
    def bulk_upload_images(self,
                          image_sources: List[Dict],
                          content_type: str,
                          max_workers: int = 5) -> List[Dict]:
        """
        Bulk upload multiple images in parallel.
        
        Args:
            image_sources: List of dicts with 'url' or 'path' and 'identifier'
            content_type: Type of content for all images
            max_workers: Number of parallel upload threads
            
        Returns:
            List of upload results
        """
        results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            
            for source in image_sources:
                if 'url' in source:
                    future = executor.submit(
                        self.upload_from_url,
                        source['url'],
                        content_type,
                        source.get('identifier', 'unknown')
                    )
                elif 'path' in source:
                    future = executor.submit(
                        self.upload_from_local,
                        source['path'],
                        content_type,
                        source.get('identifier', 'unknown')
                    )
                else:
                    continue
                    
                futures.append((future, source))
            
            for future, source in futures:
                try:
                    result = future.result(timeout=60)
                    if result:
                        result['source'] = source
                        results.append(result)
                except Exception as e:
                    logger.error(f"Bulk upload failed for {source}: {e}")
                    results.append({
                        'source': source,
                        'error': str(e),
                        'status': 'failed'
                    })
        
        return results
    
    def download_from_s3(self, s3_key: str) -> Optional[bytes]:
        """
        Download file from S3.
        
        Args:
            s3_key: S3 key of the file
            
        Returns:
            File data or None if failed
        """
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return response['Body'].read()
            
        except ClientError as e:
            logger.error(f"Failed to download from S3: {e}")
            return None
    
    def delete_from_s3(self, s3_key: str) -> bool:
        """
        Delete file from S3.
        
        Args:
            s3_key: S3 key of the file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            logger.info(f"Deleted from S3: {s3_key}")
            return True
            
        except ClientError as e:
            logger.error(f"Failed to delete from S3: {e}")
            return False
    
    def get_presigned_url(self, s3_key: str, expiration: int = 3600) -> Optional[str]:
        """
        Generate a presigned URL for temporary access.
        
        Args:
            s3_key: S3 key of the file
            expiration: URL expiration time in seconds
            
        Returns:
            Presigned URL or None if failed
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expiration
            )
            return url
            
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None
    
    def list_objects(self, prefix: str, max_results: int = 100) -> List[Dict]:
        """
        List objects in S3 with given prefix.
        
        Args:
            prefix: S3 key prefix to filter
            max_results: Maximum number of results
            
        Returns:
            List of object metadata
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_results
            )
            
            objects = []
            for obj in response.get('Contents', []):
                objects.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'url': f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{obj['Key']}"
                })
            
            return objects
            
        except ClientError as e:
            logger.error(f"Failed to list S3 objects: {e}")
            return []


# Singleton instance getter
_s3_service = None

def get_s3_service() -> S3Service:
    """
    Get singleton instance of S3 service.
    
    Returns:
        S3Service: Singleton service instance
    """
    global _s3_service
    if _s3_service is None:
        _s3_service = S3Service()
    return _s3_service


# Utility functions for common operations
def upload_restaurant_image(image_data: bytes, restaurant_name: str, **kwargs) -> Optional[Dict]:
    """Convenience function to upload restaurant image."""
    s3_service = get_s3_service()
    return s3_service.upload_image(
        image_data=image_data,
        content_type='restaurant_images',
        identifier=restaurant_name,
        **kwargs
    )


def upload_menu_image(image_data: bytes, restaurant_name: str, **kwargs) -> Optional[Dict]:
    """Convenience function to upload menu image."""
    s3_service = get_s3_service()
    return s3_service.upload_image(
        image_data=image_data,
        content_type='menu_images',
        identifier=restaurant_name,
        **kwargs
    )


def migrate_local_images_to_s3(local_directory: str, content_type: str = 'restaurant_images') -> List[Dict]:
    """
    Migrate existing local images to S3.
    
    Args:
        local_directory: Directory containing local images
        content_type: S3 content type for organization
        
    Returns:
        List of migration results
    """
    s3_service = get_s3_service()
    
    local_dir = Path(local_directory)
    if not local_dir.exists():
        logger.error(f"Local directory not found: {local_directory}")
        return []
    
    image_sources = []
    for image_path in local_dir.rglob('*'):
        if image_path.is_file() and image_path.suffix.lower() in s3_service.supported_formats:
            # Extract identifier from path
            identifier = image_path.parent.name or 'unknown'
            image_sources.append({
                'path': str(image_path),
                'identifier': identifier
            })
    
    logger.info(f"Found {len(image_sources)} images to migrate")
    
    # Bulk upload
    results = s3_service.bulk_upload_images(image_sources, content_type)
    
    # Summary
    successful = len([r for r in results if 'error' not in r])
    failed = len([r for r in results if 'error' in r])
    
    logger.info(f"Migration complete: {successful} successful, {failed} failed")
    
    return results