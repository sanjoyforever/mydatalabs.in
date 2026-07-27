# Google Cloud Run Deployment Guide — MyDataLabs (`mydatalabs-in-app`)

This guide walks you through deploying **MyDataLabs** to **Google Cloud Run** under project **`mydatalabs-in-app`**.

---

## 📌 Project Summary

- **GCP Project ID**: `mydatalabs-in-app`
- **GCP Project Name**: `MyDataLabs Intelligence`
- **GCP Project Number**: `79454230427`

---

## 🚀 2-Step Deployment Process

### Step 1: Enable Billing on GCP Console
Google Cloud requires an active billing account (with Google's $300 free trial or standard tier) to deploy serverless containers:

1. Open **[https://console.cloud.google.com/billing](https://console.cloud.google.com/billing)**.
2. Select or link project **`mydatalabs-in-app`** to your active Billing Account.

---

### Step 2: Deploy Container to Cloud Run (1-Click Command)

Run our automated PowerShell script in your project directory:

```powershell
.\deploy-cloudrun.ps1
```

Or execute directly with `gcloud`:

```powershell
# 1. Enable Cloud Run & Cloud Build APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project mydatalabs-in-app

# 2. Deploy Container from Source
gcloud run deploy mydatalabs-in `
    --project mydatalabs-in-app `
    --source . `
    --region us-central1 `
    --platform managed `
    --allow-unauthenticated `
    --memory 512Mi `
    --cpu 1 `
    --max-instances 10
```

---

## 🌐 Custom Domain Setup (`mydatalabs.in`)

To map **`https://mydatalabs.in`** to your Google Cloud Run service:

1. Open **[GCP Console — Cloud Run Custom Domains](https://console.cloud.google.com/run/domains)**.
2. Click **Add Mapping** -> Select **`mydatalabs-in`** service.
3. Enter domain **`mydatalabs.in`**.
4. Copy the generated CNAME / A records into your domain DNS provider (Cloudflare / Namecheap / GoDaddy).
