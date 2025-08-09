#!/usr/bin/env python3
"""
Test restaurant summary functionality
"""
import os
import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).resolve().parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')
import django
django.setup()

try:
    from templates import get_summary_prompt, summary_prompt
    print("✅ Templates imported successfully")
except ImportError as e:
    print(f"❌ Templates import failed: {e}")

try:
    from token_management.token_manager import call_openai_chat
    print("✅ Token manager imported successfully")
except ImportError as e:
    print(f"❌ Token manager import failed: {e}")

# Test basic summary
def test_summary():
    print("\n🧪 Testing restaurant summary...")
    
    test_content = """
    Le Bernardin is a renowned seafood restaurant in New York City.
    Chef Eric Ripert serves exquisite French cuisine focused on fish.
    The restaurant has 3 Michelin stars and is located in Midtown Manhattan.
    """
    
    test_url = "https://guide.michelin.com/us/en/new-york-state/new-york/restaurant/le-bernardin"
    
    try:
        user_prompt = get_summary_prompt(test_url, test_content)
        print(f"✅ User prompt generated: {len(user_prompt)} chars")
        
        # Test call_openai_chat directly
        response = call_openai_chat(
            system_prompt=summary_prompt,
            user_prompt=user_prompt,
            force_model="gpt-4o-mini",
            response_format={"type": "json_object"}
        )
        
        print(f"✅ LLM response: {response}")
        
    except Exception as e:
        print(f"❌ Summary test failed: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    test_summary()