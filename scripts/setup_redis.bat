@echo off
:: Phase 7: Setup Redis Dev Environment for Windows
:: Requires Docker Desktop

echo Starting OpsSentry Redis environment...
docker-compose up -d redis

:: Wait for redis to be ready
echo Waiting for Redis to be ready...
:check_redis
docker exec opssentry-redis redis-cli ping | findstr PONG >nul
if %errorlevel% neq 0 (
    timeout /t 1 /nobreak >nul
    goto check_redis
)

echo Redis is ready at redis://localhost:6379
echo To use Redis in OpsSentry, set REDIS_URL=redis://localhost:6379
