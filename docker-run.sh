#!/usr/bin/env bash
# Docker Launch Script for MyDataLabs (Bash/Linux/macOS)
echo "=================================================="
echo "Building & Launching MyDataLabs Docker Container..."
echo "=================================================="

docker compose up --build -d

echo ""
echo "=================================================="
echo "MyDataLabs Container Active at: http://localhost:5000"
echo "Hormuz Crisis Index: http://localhost:5000/hormuz-index"
echo "=================================================="
