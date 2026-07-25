# MyDataLabs — Institutional Geopolitical Risk & Quantitative Intelligence Network

[![Flask Application](https://img.shields.io/badge/Framework-Flask_3.0-blue?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)
[![Apache ECharts](https://img.shields.io/badge/Visualization-Apache_ECharts_5.5-cyan?style=flat-square&logo=apache)](https://echarts.apache.org/)
[![Vercel Deployment](https://img.shields.io/badge/Deployment-Vercel_Serverless-black?style=flat-square&logo=vercel)](https://vercel.com/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

**MyDataLabs** is a media-grade quantitative intelligence platform tracking geopolitical risk, energy security, and maritime chokepoints. Its flagship index, the **Hormuz Crisis Index (HMX-INDEX)**, provides quantitative metrics for financial analysts, commodity traders, and international news outlets covering Middle East shipping disruptions.

---

## 🚀 Key Features

- **Hormuz Crisis Index (HMX-INDEX)**: Weekly composite stress score normalized against a calm baseline (Feb 1–5, 2026 = 100.0).
- **Apache ECharts Visualizations**: Canvas-rendered dynamic charts:
  - **Weekly Trajectory Line Chart** (100.0 Baseline & Ceasefire markers)
  - **Attacks by Country (Flag State)** distribution bar chart
  - **Cumulative Vessel Attacks by Month** running total area chart
- **Targeted Vessel Attacks Intelligence**: Database tracking 56 maritime strike incidents (Feb – Jul 2026) with flag state, vessel type, strike method, and location.
- **Ready-to-Publish 300-Word Press Wire Dispatch**: One-click copyable news report formatted for newsrooms (Reuters, AP, Bloomberg, FT).
- **Vercel Serverless Architecture**: Configured with `api/index.py` WSGI wrapper for Vercel deployment.

---

## 📊 Composite Index Math & Components

$$\text{Index Score} = 100.0 + \sum \Big[ \text{Weight}_i \times \text{StressScore}(\text{Current}_i, \text{Baseline}_i, \text{Cap}_i) \Big]$$

| Component | Weight | Baseline Value | Stress Cap | Data Source |
| :--- | :---: | :---: | :---: | :--- |
| **Brent Crude Oil** | **30%** | $65.00 / bbl | +55% | yfinance (`BZ=F`) |
| **Hormuz Ship Traffic** | **15%** | 34 transits / wk | -50% (Inverted) | Lloyd's List Intelligence |
| **War-Risk Insurance** | **15%** | 0.10% hull value | +400% | Reuters / S&P Global |
| **Tanker Freight (BDTI)** | **15%** | 900 index points | +75% | Baltic Exchange |
| **TTF European Gas** | **10%** | 33.0 EUR / MWh | +95% | yfinance (`TTF=F`) |
| **VIX Volatility Index** | **10%** | 14.50 index points | +200% | yfinance (`^VIX`) |
| **Cape Reroutes** | **5%** | 8.0% of traffic | +250% | AIS / Vortexa Data |

---

## 📂 Project Structure

```
mydatalabs-in/
├── api/
│   └── index.py            # Vercel serverless WSGI entry point
├── app/
│   ├── data/
│   │   ├── hormuz_history.json  # 29-week composite index history
│   │   └── vessel_attacks.json  # 56 verified maritime strike incidents
│   ├── indices/
│   │   └── hormuz.py       # Indicator definitions & live fetcher
│   ├── static/
│   │   ├── css/style.css   # Glassmorphic dark/light CSS tokens
│   │   ├── js/theme.js     # Tooltip & theme toggler
│   │   └── img/            # Logo & Favicon assets
│   ├── templates/
│   │   ├── base.html       # Layout template with ECharts & branding
│   │   ├── home.html       # Landing page & index overview
│   │   └── hormuz.html     # HMX-INDEX intelligence dashboard
│   ├── routes.py           # Blueprint routing & dataset aggregations
│   └── scoring.py          # Stress score normalization engine
├── update_data.py          # Standalone data updater script
├── app.py                  # Local Flask dev server entrypoint
├── requirements.txt        # Python dependencies
├── vercel.json             # Vercel routes & serverless config
└── README.md               # Repository documentation
```

---

## 🛠️ Local Development & Data Update

### 1. Install Dependencies
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run Local Development Server
```bash
python app.py
```
Open `http://127.0.0.1:5000` in your web browser.

### 3. Run Automated Data Updater
```bash
python update_data.py
```

---

## 🌐 Deploying to Vercel & GoDaddy DNS Setup

### 1. Push Code to GitHub
```bash
git init
git add .
git commit -m "Initial commit: MyDataLabs quantitative intelligence platform"
git remote add origin https://github.com/sanjoyforever/mydatalabs.in.git
git branch -M main
git push -u origin main
```

### 2. Deploy on Vercel
```bash
npx vercel --prod
```
Or connect `sanjoyforever/mydatalabs.in` in the [Vercel Dashboard](https://vercel.com/dashboard).

### 3. Add Custom Domain on Vercel
In Vercel Project Settings → **Domains**:
- Add domain: `mydatalabs.in`
- Add domain: `www.mydatalabs.in`

### 4. GoDaddy DNS Configuration
In GoDaddy DNS Management for `mydatalabs.in`:

| Type | Name / Host | Value / Points To | TTL |
| :--- | :--- | :--- | :--- |
| **A Record** | `@` | `76.76.21.21` | 1 Hour / Automatic |
| **CNAME** | `www` | `cname.vercel-dns.com` | 1 Hour / Automatic |

---

## 📄 License & Attribution

© 2026 MyDataLabs Intelligence Network. Data provided for research, financial modeling, and news media reporting.  
Attribution: *MyDataLabs Hormuz Crisis Index (HMX-INDEX) — mydatalabs.in*.
