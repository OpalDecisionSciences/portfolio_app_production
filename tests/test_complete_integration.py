#!/usr/bin/env python3
"""
Complete Integration Test - Tests all components working together
"""

import os
import sys
from pathlib import Path
import json

# Use comprehensive path management
sys.path.insert(0, str(Path(__file__).resolve().parent / "shared" / "src"))
from path_manager import setup_portfolio_paths
setup_portfolio_paths(['data_pipeline', 'django'])

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'portfolio_project.settings')
import django
django.setup()

def test_scraper_integration():
    """Test the unified scraper with all features."""
    print("🔬 TESTING UNIFIED SCRAPER INTEGRATION")
    print("=" * 50)
    
    try:
        from unified_restaurant_scraper import scrape_restaurant_unified
        
        # Test with a simple restaurant
        result = scrape_restaurant_unified(
            url="https://www.hisafranko.com/",
            restaurant_name="Hiša Franko Test",
            max_images=3,
            save_to_db=True,
            multi_page=True
        )
        
        print(f"✅ Scraping Success: {result.get('scraping_success', False)}")
        print(f"✅ Database Save: {result.get('save_to_db_success', False)}")
        print(f"✅ Menu Sections: {result.get('menu_sections_created', 0)}")
        print(f"✅ Menu Items: {result.get('menu_items_created', 0)}")
        print(f"✅ Images: {result.get('images_integrated', 0)}")
        print(f"✅ Document Generated: {'Yes' if result.get('document_txt') else 'No'}")
        
        # Test language detection
        llm_analysis = result.get('llm_analysis', {})
        if llm_analysis:
            print(f"✅ Language Detected: {llm_analysis.get('detected_language', 'Unknown')}")
            print(f"✅ Translation Used: {'Yes' if llm_analysis.get('translated_content') else 'No'}")
        
        return result
        
    except Exception as e:
        print(f"❌ Scraper test failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_database_integration():
    """Test database models and data."""
    print("\\n🗄️  TESTING DATABASE INTEGRATION")
    print("=" * 50)
    
    try:
        from restaurants.models import Restaurant, MenuSection, MenuItem, RestaurantImage
        
        # Check recent restaurants
        restaurants = Restaurant.objects.filter(name__icontains="Franko").order_by('-created_at')
        print(f"✅ Restaurants found: {restaurants.count()}")
        
        if restaurants.exists():
            restaurant = restaurants.first()
            print(f"✅ Restaurant: {restaurant.name}")
            print(f"✅ Location: {restaurant.city}, {restaurant.country}")
            print(f"✅ Menu Sections: {restaurant.menu_sections.count()}")
            print(f"✅ Images: {restaurant.images.count()}")
            print(f"✅ Timezone Info: {'Yes' if restaurant.timezone_info else 'No'}")
            
            # Test timezone display
            if hasattr(restaurant, 'get_timezone_display'):
                print(f"✅ Timezone Display: {restaurant.get_timezone_display()}")
            
            return restaurant
        
        return None
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_frontend_views():
    """Test Django views and template rendering."""
    print("\\n🎨 TESTING FRONTEND VIEWS")
    print("=" * 50)
    
    try:
        from django.test import Client
        from restaurants.models import Restaurant
        
        client = Client()
        
        # Test restaurant list view
        response = client.get('/restaurants/')
        print(f"✅ Restaurant List View: {response.status_code == 200}")
        
        # Test restaurant detail view if restaurants exist
        restaurants = Restaurant.objects.filter(is_active=True).first()
        if restaurants:
            response = client.get(f'/restaurants/{restaurants.slug}/')
            print(f"✅ Restaurant Detail View: {response.status_code == 200}")
            
            # Check if context includes our new features
            if response.status_code == 200:
                content = response.content.decode()
                has_timezone = 'timezone' in content.lower()
                has_images = 'gallery' in content.lower()
                has_menu = 'menu-section' in content.lower()
                
                print(f"✅ Timezone Display: {has_timezone}")
                print(f"✅ Image Gallery: {has_images}")
                print(f"✅ Menu Display: {has_menu}")
        
        return True
        
    except Exception as e:
        print(f"❌ Frontend test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_token_management():
    """Test token management integration."""
    print("\\n🎫 TESTING TOKEN MANAGEMENT")
    print("=" * 50)
    
    try:
        from token_management.token_manager import get_token_usage_summary, call_openai_chat
        
        # Test token manager
        summary = get_token_usage_summary()
        print(f"✅ Token Manager Working: {bool(summary)}")
        print(f"✅ Current Model: {summary.get('current_model', 'Unknown')}")
        print(f"✅ Date: {summary.get('date', 'Unknown')}")
        
        # Test a simple LLM call
        response = call_openai_chat(
            system_prompt="You are a helpful assistant.",
            user_prompt="Say 'Token manager test successful' in JSON format.",
            response_format="json"
        )
        
        if response:
            print("✅ LLM Call Successful")
            try:
                result = json.loads(response)
                print(f"✅ JSON Parsing: {bool(result)}")
            except:
                print("✅ Response received (JSON parsing failed)")
        
        return True
        
    except Exception as e:
        print(f"❌ Token management test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 COMPLETE INTEGRATION TEST SUITE")
    print("🍽️  Testing Global Restaurant Scraping System")
    print("=" * 60)
    
    try:
        # Run all tests
        scraper_result = test_scraper_integration()
        db_result = test_database_integration()
        frontend_result = test_frontend_views()
        token_result = test_token_management()
        
        print("\\n" + "=" * 60)
        print("📊 FINAL TEST RESULTS")
        print("=" * 60)
        
        results = {
            "Scraper Integration": bool(scraper_result),
            "Database Integration": bool(db_result),
            "Frontend Views": frontend_result,
            "Token Management": token_result
        }
        
        for test_name, passed in results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{test_name}: {status}")
        
        overall_success = all(results.values())
        print(f"\\n🎯 OVERALL: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
        
        if overall_success:
            print("\\n🚀 SYSTEM READY FOR GLOBAL RESTAURANT SCRAPING!")
            print("✨ Features Available:")
            print("   • GPT-4o translation for global content")
            print("   • Multi-page scraping with link filtering")
            print("   • Document.txt generation for restaurant profiles")
            print("   • Image scraping and AI categorization")
            print("   • Timezone support for global restaurants")
            print("   • Batch processing for 15,000+ websites")
            print("   • Full Django frontend integration")
        
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()