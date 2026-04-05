#!/bin/bash
# Phase 7: Setup Redis Dev Environment
# Requires docker and docker-compose

echo "Starting OpsSentry Redis environment..."
docker-compose up -d redis

# Wait for redis to be ready
echo "Waiting for Redis to be ready..."
until docker exec opssentry-redis redis-cli ping | grep -q PONG; do
    sleep 1
done

echo "Redis is ready at redis://localhost:6379"
echo "To use Redis in OpsSentry, set REDIS_URL=redis://localhost:6379"
