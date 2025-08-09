"""
Comprehensive Path Management for Portfolio Application
Combines functionality from config.py and path_setup.py with enhanced modularity.
"""
import sys
import os
from pathlib import Path
import importlib.util
from typing import List, Union, Dict, Any, Optional

# Get the portfolio app root directory
PORTFOLIO_ROOT = Path(__file__).resolve().parent.parent.parent

# Component paths
DJANGO_APP_ROOT = PORTFOLIO_ROOT / "django_app" / "src"
DATA_PIPELINE_ROOT = PORTFOLIO_ROOT / "data_pipeline" / "src"
RAG_SERVICE_ROOT = PORTFOLIO_ROOT / "rag_service" / "src"
SHARED_ROOT = PORTFOLIO_ROOT / "shared" / "src"

# Track initialization state per component
_component_initialized = {
    'shared': False,
    'django': False,
    'data_pipeline': False,
    'rag_service': False
}

def setup_portfolio_paths(
    components: Union[str, List[str]] = 'all', 
    verbose: bool = False,
    force: bool = False
) -> List[str]:
    """
    Setup Python paths for portfolio application components.
    
    Args:
        components: Components to setup. Options:
            - 'all': All components (default, backward compatible)
            - 'django': Django models, forms, views, admin
            - 'data_pipeline': Scrapers, processors, utilities
            - 'rag_service': Embeddings, retrieval, search
            - 'shared': Token management, utilities (always included)
            - List of specific components: ['django', 'shared']
        verbose: Print detailed setup information
        force: Force re-initialization even if already done
        
    Returns:
        List of paths that were added to sys.path
    """
    global _component_initialized
    
    # Normalize components to list
    if components == 'all':
        components_list = ['shared', 'django', 'data_pipeline', 'rag_service']
    elif isinstance(components, str):
        components_list = [components]
    else:
        components_list = list(components)
    
    # Always include shared
    if 'shared' not in components_list:
        components_list.insert(0, 'shared')
    
    added_paths = []
    
    for component in components_list:
        if not force and _component_initialized.get(component, False):
            if verbose:
                print(f"  ✓ {component} already initialized")
            continue
            
        paths_added = _setup_component_paths(component, verbose)
        added_paths.extend(paths_added)
        _component_initialized[component] = True
        
        if verbose:
            print(f"  ✓ {component} initialized ({len(paths_added)} paths)")
    
    if verbose:
        print(f"Portfolio paths setup complete: {len(added_paths)} total paths added")
        
    return added_paths

def _setup_component_paths(component: str, verbose: bool = False) -> List[str]:
    """Setup paths for a specific component."""
    added_paths = []
    
    if component == 'shared':
        paths = [
            str(PORTFOLIO_ROOT),
            str(SHARED_ROOT),
        ]
        # Ensure token management is accessible
        token_mgmt_path = SHARED_ROOT / "token_management"
        if token_mgmt_path.exists():
            paths.append(str(token_mgmt_path.parent))
            
    elif component == 'django':
        paths = [
            str(DJANGO_APP_ROOT),
            str(DJANGO_APP_ROOT / "portfolio_project"),
            str(DJANGO_APP_ROOT / "restaurants"), 
            str(DJANGO_APP_ROOT / "accounts"),
            str(DJANGO_APP_ROOT / "chat"),
        ]
        
    elif component == 'data_pipeline':
        paths = [
            str(DATA_PIPELINE_ROOT),
            str(DATA_PIPELINE_ROOT / "scrapers"),
            str(DATA_PIPELINE_ROOT / "processors"),
            str(DATA_PIPELINE_ROOT / "ingestion"),
        ]
        
    elif component == 'rag_service':
        paths = [
            str(RAG_SERVICE_ROOT),
            str(RAG_SERVICE_ROOT / "api"),
            str(RAG_SERVICE_ROOT / "embeddings"),
            str(RAG_SERVICE_ROOT / "retrieval"),
            str(RAG_SERVICE_ROOT / "tools"),
            str(RAG_SERVICE_ROOT / "scripts"),
        ]
        
    else:
        if verbose:
            print(f"  ⚠ Unknown component: {component}")
        return []
    
    # Add paths to sys.path if not already present
    for path in paths:
        if path not in sys.path:
            sys.path.insert(0, path)
            added_paths.append(path)
            if verbose:
                print(f"    + Added: {path}")
    
    return added_paths

def get_project_root() -> Path:
    """Get the portfolio app root directory."""
    return PORTFOLIO_ROOT

def get_component_root(component: str) -> Optional[Path]:
    """Get the root directory for a specific component."""
    roots = {
        'django': DJANGO_APP_ROOT,
        'data_pipeline': DATA_PIPELINE_ROOT,
        'rag_service': RAG_SERVICE_ROOT,
        'shared': SHARED_ROOT
    }
    return roots.get(component)

def safe_import(module_name: str, package: Optional[str] = None, fallback: Any = None) -> Any:
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

def check_external_dependencies() -> Dict[str, bool]:
    """
    Check if external dependencies are available.
    
    Returns:
        dict: Status of each dependency
    """
    dependencies = [
        'openai', 'tiktoken', 'selenium', 'langdetect', 
        'pandas', 'dotenv', 'bs4', 'webdriver_manager',
        'django', 'langchain_openai', 'langchain_postgres',
        'psycopg', 'celery', 'redis'
    ]
    
    status = {}
    for dep in dependencies:
        try:
            importlib.import_module(dep)
            status[dep] = True
        except ImportError:
            status[dep] = False
    
    return status

def get_missing_dependencies() -> List[str]:
    """Get list of missing external dependencies."""
    status = check_external_dependencies()
    return [dep for dep, available in status.items() if not available]

def verify_component_setup(component: str) -> Dict[str, Any]:
    """
    Verify that a component is properly setup and accessible.
    
    Args:
        component: Component name to verify
        
    Returns:
        Dictionary with verification results
    """
    result = {
        'component': component,
        'initialized': _component_initialized.get(component, False),
        'root_exists': False,
        'key_modules': {},
        'status': 'unknown'
    }
    
    # Check if component root exists
    root = get_component_root(component)
    if root:
        result['root_exists'] = root.exists()
    
    # Test key module imports for each component
    test_imports = {
        'django': ['restaurants.models', 'portfolio_project.settings'],
        'data_pipeline': ['token_management.token_manager'],
        'rag_service': ['api.main'],
        'shared': ['token_management.token_manager']
    }
    
    if component in test_imports:
        for module in test_imports[component]:
            try:
                importlib.import_module(module)
                result['key_modules'][module] = True
            except ImportError as e:
                result['key_modules'][module] = f"Error: {e}"
    
    # Determine overall status
    if result['initialized'] and result['root_exists']:
        failed_imports = [k for k, v in result['key_modules'].items() if v is not True]
        if not failed_imports:
            result['status'] = 'healthy'
        else:
            result['status'] = 'partial'
    else:
        result['status'] = 'failed'
    
    return result

def get_setup_status() -> Dict[str, Any]:
    """Get current setup status for all components."""
    return {
        'portfolio_root': str(PORTFOLIO_ROOT),
        'components': {
            comp: _component_initialized[comp] 
            for comp in ['shared', 'django', 'data_pipeline', 'rag_service']
        },
        'sys_path_count': len(sys.path),
        'missing_dependencies': get_missing_dependencies()
    }

def reset_initialization(components: Union[str, List[str]] = 'all') -> None:
    """
    Reset initialization state for components.
    Useful for testing or when paths need to be reconfigured.
    
    Args:
        components: Components to reset ('all' or list of component names)
    """
    global _component_initialized
    
    if components == 'all':
        for comp in _component_initialized:
            _component_initialized[comp] = False
    elif isinstance(components, str):
        if components in _component_initialized:
            _component_initialized[components] = False
    else:
        for comp in components:
            if comp in _component_initialized:
                _component_initialized[comp] = False

# Backward compatibility functions
def setup_django_paths(verbose: bool = False) -> List[str]:
    """Setup Django-specific paths. Backward compatibility function."""
    return setup_portfolio_paths(['django'], verbose=verbose)

def setup_data_pipeline_paths(verbose: bool = False) -> List[str]:
    """Setup data pipeline specific paths. Backward compatibility function."""
    return setup_portfolio_paths(['data_pipeline'], verbose=verbose)

def setup_rag_service_paths(verbose: bool = False) -> List[str]:
    """Setup RAG service specific paths. Backward compatibility function.""" 
    return setup_portfolio_paths(['rag_service'], verbose=verbose)

def setup_portfolio_paths_legacy(force: bool = False) -> None:
    """Legacy function from config.py for backward compatibility."""
    setup_portfolio_paths('all', force=force)

if __name__ == "__main__":
    # Demo and testing
    print("=== Portfolio Path Manager Demo ===")
    print(f"Portfolio Root: {PORTFOLIO_ROOT}")
    print(f"Components Available: {list(_component_initialized.keys())}")
    
    print("\n--- Testing Component Setup ---")
    for component in ['shared', 'django', 'data_pipeline', 'rag_service']:
        paths_added = setup_portfolio_paths([component], verbose=True)
        verification = verify_component_setup(component)
        print(f"{component}: {verification['status']} ({len(paths_added)} paths)")
    
    print("\n--- Current Status ---")
    status = get_setup_status()
    for key, value in status.items():
        print(f"{key}: {value}")
    
    print("\n--- Missing Dependencies ---")
    missing = get_missing_dependencies()
    if missing:
        print(f"Missing: {', '.join(missing)}")
    else:
        print("All dependencies available!")