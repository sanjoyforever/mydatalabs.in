# Docker Launch Script for MyDataLabs (PowerShell)
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Building & Launching MyDataLabs Docker Container..." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan

docker compose up --build -d

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "MyDataLabs Container Active at: http://localhost:5000" -ForegroundColor Green
Write-Host "Hormuz Crisis Index: http://localhost:5000/hormuz-index" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
