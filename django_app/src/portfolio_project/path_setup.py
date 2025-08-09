"""
Python path setup for shared modules.
This module ensures that shared modules are accessible in Django.
"""
import sys
import os
from pathlib import Path

def setup_shared_paths():
    """
    Add shared module paths to Python path for Django application.
    This ensures UnifiedSearchFilters and other shared modules are accessible.
    """
    # Get the project root directory
    django_src = Path(__file__).resolve().parent.parent  # django_app/src
    django_app = django_src.parent  # django_app
    project_root = django_app.parent  # portfolio_app_production
    
    # Add shared paths
    shared_src = project_root / 'shared' / 'src'
    data_pipeline_src = project_root / 'data_pipeline' / 'src'
    
    # Add to Python path if not already present
    for path in [shared_src, data_pipeline_src]:
        path_str = str(path)
        if path_str not in sys.path and path.exists():
            sys.path.insert(0, path_str)
            print(f"Added to Python path: {path_str}")
    
    return True

# Auto-setup when imported
setup_shared_paths()