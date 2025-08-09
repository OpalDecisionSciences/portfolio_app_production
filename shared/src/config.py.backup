"""
Centralized configuration for portfolio app paths and imports.
"""
import sys
import os
from pathlib import Path
import importlib.util

# Get the portfolio app root directory
PORTFOLIO_ROOT = Path(__file__).resolve().parent.parent.parent

# Component paths
DJANGO_APP_ROOT = PORTFOLIO_ROOT / "django_app" / "src"
DATA_PIPELINE_ROOT = PORTFOLIO_ROOT / "data_pipeline" / "src"
RAG_SERVICE_ROOT = PORTFOLIO_ROOT / "rag_service" / "src"
SHARED_ROOT = PORTFOLIO_ROOT / "shared" / "src"

# Track if paths have been set up
_paths_initialized = False

def setup_portfolio_paths(force=False):
    """
    Add all portfolio app components to Python path.
    Call this function before importing any portfolio modules.
    
    Args:
        force: Force re-initialization even if already done
    """
    global _paths_initialized
    
    if _paths_initialized and not force:
        return
    
    paths_to_add = [
        str(PORTFOLIO_ROOT),
        str(DJANGO_APP_ROOT),
        str(DATA_PIPELINE_ROOT),
        str(RAG_SERVICE_ROOT),
        str(SHARED_ROOT)
    ]
    
    for path in paths_to_add:
        if path not in sys.path:
            sys.path.insert(0, path)
    
    _paths_initialized = True
    
    # Verify token_management is accessible
    token_mgmt_path = SHARED_ROOT / "token_management"
    if token_mgmt_path.exists():
        token_mgmt_str = str(token_mgmt_path.parent)
        if token_mgmt_str not in sys.path:
            sys.path.insert(0, token_mgmt_str)

def get_project_root():
    """Get the portfolio app root directory."""
    return PORTFOLIO_ROOT

def safe_import(module_name, package=None, fallback=None):
    """
    Safely import a module with fallback options.
    
    Args:
        module_name: Name of module to import
        package: Package name for relative imports
        fallback: Fallback value if import fails
    
    Returns:
        Imported module or fallback value
    """
    try:
        if package:
            return importlib.import_module(module_name, package)
        else:
            return importlib.import_module(module_name)
    except ImportError as e:
        print(f"Warning: Could not import {module_name}: {e}")
        return fallback

def check_external_dependencies():
    """
    Check if external dependencies are available.
    
    Returns:
        dict: Status of each dependency
    """
    dependencies = [
        'openai', 'tiktoken', 'selenium', 'langdetect', 
        'pandas', 'dotenv', 'bs4', 'webdriver_manager'
    ]
    
    status = {}
    for dep in dependencies:
        try:
            importlib.import_module(dep)
            status[dep] = True
        except ImportError:
            status[dep] = False
    
    return status

def get_missing_dependencies():
    """Get list of missing external dependencies."""
    status = check_external_dependencies()
    return [dep for dep, available in status.items() if not available]