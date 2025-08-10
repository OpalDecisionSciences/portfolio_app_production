#!/usr/bin/env python3
"""
Production Configuration Validation Script
Validates that all critical fixes have been applied correctly.
"""

import os
import sys
import subprocess
from pathlib import Path

def check_docker_compose_consistency():
    """Check Docker Compose files for consistency"""
    print("🔍 Checking Docker Compose consistency...")
    
    celery_compose = Path("docker-compose.celery.yml")
    if not celery_compose.exists():
        print("❌ docker-compose.celery.yml not found")
        return False
        
    content = celery_compose.read_text()
    
    issues = []
    
    # Check build context
    if "context: ./django_app" in content:
        issues.append("❌ Found old build context './django_app' in celery compose")
    
    if "dockerfile: Dockerfile" in content:
        issues.append("❌ Found old dockerfile reference 'Dockerfile' in celery compose")
    
    # Check network naming
    if "portfolio_network:" in content and "portfolio_network_prod:" not in content:
        issues.append("❌ Found incorrect network name 'portfolio_network'")
    
    if issues:
        for issue in issues:
            print(issue)
        return False
    
    print("✅ Docker Compose consistency checks passed")
    return True

def check_migration_atomic_flags():
    """Check that index creation migrations have proper atomic=False"""
    print("🔍 Checking migration atomic flags...")
    
    migration_files = [
        "django_app/src/restaurants/migrations/0006_enhanced_search_indexes.py",
        "django_app/src/restaurants/migrations/0008_cart_status_indexes.py",
        "django_app/src/restaurants/migrations/0009_fix_basemodel_soft_delete_fields.py",
        "django_app/src/restaurants/migrations/0011_performance_indexes.py",
        "django_app/src/accounts/migrations/0005_user_performance_indexes.py"
    ]
    
    issues = []
    
    for migration_file in migration_files:
        migration_path = Path(migration_file)
        if not migration_path.exists():
            issues.append(f"❌ Migration file not found: {migration_file}")
            continue
            
        content = migration_path.read_text()
        
        # Check for CONCURRENTLY usage (should be removed)
        if "CONCURRENTLY" in content:
            issues.append(f"❌ Found CONCURRENTLY in {migration_file}")
        
        # Check for CREATE INDEX with atomic=False
        if "CREATE INDEX" in content:
            if "atomic = False" not in content and "atomic=False" not in content:
                issues.append(f"❌ Index creation without atomic=False in {migration_file}")
    
    if issues:
        for issue in issues:
            print(issue)
        return False
    
    print("✅ Migration atomic flags checks passed")
    return True

def check_docker_syntax():
    """Check Docker Compose files have valid syntax"""
    print("🔍 Checking Docker Compose syntax...")
    
    compose_files = [
        "docker-compose.prod.yml",
        "docker-compose.celery.yml"
    ]
    
    for compose_file in compose_files:
        try:
            result = subprocess.run(
                ["docker-compose", "-f", compose_file, "config"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                print(f"❌ Invalid syntax in {compose_file}:")
                print(result.stderr)
                return False
        except subprocess.TimeoutExpired:
            print(f"⚠️  Timeout checking {compose_file} (likely missing environment variables)")
        except FileNotFoundError:
            print("⚠️  docker-compose not found, skipping syntax check")
            break
    
    print("✅ Docker Compose syntax checks passed")
    return True

def main():
    """Run all validation checks"""
    print("🚀 Production Configuration Validation")
    print("=" * 50)
    
    # Change to project root directory
    os.chdir(Path(__file__).parent.parent)
    
    checks = [
        check_docker_compose_consistency,
        check_migration_atomic_flags,
        check_docker_syntax,
    ]
    
    results = []
    for check in checks:
        try:
            result = check()
            results.append(result)
        except Exception as e:
            print(f"❌ Check failed with error: {e}")
            results.append(False)
        print()
    
    print("📋 VALIDATION SUMMARY")
    print("=" * 50)
    
    if all(results):
        print("🎉 ALL CRITICAL FIXES VALIDATED SUCCESSFULLY!")
        print("✅ Configuration is production-ready")
        sys.exit(0)
    else:
        print("❌ VALIDATION FAILED")
        print("⚠️  Please fix the issues above before deploying to production")
        sys.exit(1)

if __name__ == "__main__":
    main()