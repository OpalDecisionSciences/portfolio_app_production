#!/bin/bash

echo "🔍 PRODUCTION SERVER DIAGNOSTIC SCRIPT"
echo "======================================"
echo "Timestamp: $(date)"
echo ""

echo "🐳 CONTAINER STATUS:"
docker-compose -f docker-compose.prod.yml ps
echo ""

echo "📋 CELERY WORKER LOGS (last 15 lines):"
echo "----------------------------------------"
docker logs portfolio_celery_prod --tail 15
echo ""

echo "📋 CELERY BEAT LOGS (last 15 lines):"
echo "-------------------------------------"
docker logs portfolio_celery_beat_prod --tail 15
echo ""

echo "📋 FLOWER LOGS (last 15 lines):"
echo "--------------------------------"
docker logs portfolio_flower_prod --tail 15
echo ""

echo "📋 WEB APPLICATION LOGS (last 10 lines):"
echo "-----------------------------------------"
docker logs portfolio_web_prod --tail 10
echo ""

echo "📋 NGINX LOGS (last 10 lines):"
echo "-------------------------------"
docker logs portfolio_nginx_prod --tail 10
echo ""

echo "🌐 CONNECTIVITY TESTS:"
echo "----------------------"
echo "Local HTTP test:"
curl -I http://localhost/health/ 2>&1 || echo "❌ Local HTTP failed"
echo ""

echo "Local port 80 test:"
curl -I http://localhost:80/health/ 2>&1 || echo "❌ Local port 80 failed"
echo ""

echo "🔒 SSL CERTIFICATE STATUS:"
echo "---------------------------"
docker exec portfolio_nginx_prod nginx-ssl-manager status 2>&1 || echo "❌ SSL manager failed"
echo ""

echo "🔧 NGINX CONFIGURATION TEST:"
echo "-----------------------------"
docker exec portfolio_nginx_prod nginx -t 2>&1 || echo "❌ Nginx config invalid"
echo ""

echo "🌍 DNS RESOLUTION:"
echo "------------------"
echo "Domain resolution:"
nslookup opaldecisionsciences.com 2>&1 || echo "❌ DNS lookup failed"
echo ""

echo "Domain IP:"
dig +short opaldecisionsciences.com 2>&1 || echo "❌ DNS dig failed"
echo ""

echo "Current server IP:"
curl -s http://checkip.amazonaws.com/ 2>&1 || echo "❌ IP check failed"
echo ""

echo "🔄 REDIS CONNECTION TEST:"
echo "-------------------------"
docker exec portfolio_redis_prod redis-cli ping 2>&1 || echo "❌ Redis ping failed"
echo ""

echo "💾 DATABASE CONNECTION TEST:"
echo "-----------------------------"
docker exec portfolio_web_prod python manage.py dbshell -c "SELECT 1;" 2>&1 || echo "❌ Database connection failed"
echo ""

echo "📊 SYSTEM RESOURCES:"
echo "--------------------"
echo "Memory usage:"
free -h
echo ""
echo "Disk usage:"
df -h /
echo ""
echo "Docker disk usage:"
docker system df
echo ""

echo "🎯 QUICK FIX RECOMMENDATIONS:"
echo "==============================" 
echo "If you see connection errors, try:"
echo "1. docker-compose -f docker-compose.prod.yml restart celery celery-beat flower"
echo "2. docker-compose -f docker-compose.prod.yml down && docker-compose -f docker-compose.prod.yml up -d"
echo "3. Check if domain DNS points to this server IP"
echo ""

echo "✅ DIAGNOSTIC COMPLETE"