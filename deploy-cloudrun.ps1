# Google Cloud Run Deployment Script for MyDataLabs (PowerShell)
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Deploying MyDataLabs Container to Google Cloud Run (mydatalabs-in-app)..." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan

gcloud config set project mydatalabs-in-app

# 1. Enable Required GCP APIs
Write-Host "1. Enabling Cloud Run & Cloud Build APIs..." -ForegroundColor Yellow
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project mydatalabs-in-app

# 2. Deploy Container from Source
Write-Host "2. Building & Deploying Container to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy mydatalabs-in `
    --project mydatalabs-in-app `
    --source . `
    --region us-central1 `
    --platform managed `
    --allow-unauthenticated `
    --memory 512Mi `
    --cpu 1 `
    --max-instances 10

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "MYDATALABS DEPLOYED TO GOOGLE CLOUD RUN SUCCESSFULLY!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
