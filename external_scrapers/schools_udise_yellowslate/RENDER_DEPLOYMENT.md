# 🚀 Deploying UDISE Scraper on Render.com

The UDISE scraper has been fully configured for 1-click Docker deployment on **Render.com**. It will automatically download your latest progress (1,483 PINs, 107,951 schools) from your Hugging Face Dataset (`herseiiii/udise-data`), continue scraping, and continuously save progress back to Hugging Face via Parquet files.

---

## 📋 Simple 2-Minute Deployment Steps

### Option A: Using Render Blueprints (Recommended - 1 Click)

1. Sign in to [Render.com](https://dashboard.render.com/).
2. Click **New +** -> **Blueprints**.
3. Connect your GitHub repository (`b-harshith/rancho`).
4. Render will automatically detect `render.yaml` and configure the **udise-scraper** Docker service with all environment variables pre-filled!
5. Click **Apply**.

---

### Option B: Creating a Web Service Manually

1. Sign in to [Render.com](https://dashboard.render.com/).
2. Click **New +** -> **Web Service**.
3. Select **Build and deploy from a Git repository**, and select `b-harshith/rancho`.
4. Configure the settings:
   - **Name**: `udise-scraper`
   - **Language / Environment**: `Docker`
   - **Dockerfile Path**: `external_scrapers/schools_udise_yellowslate/Dockerfile`
   - **Docker Build Context**: `external_scrapers/schools_udise_yellowslate`
   - **Instance Type**: `Free` or `Starter`
5. Add the Environment Variables:
   - `HF_TOKEN`: `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`
   - `HF_REPO`: `herseiiii/udise-data`
   - `UDISE_HEADLESS`: `1`
   - `UDISE_CHROME`: `/usr/bin/chromium`
   - `UDISE_BROWSER_CONCURRENCY`: `3`
6. Click **Create Web Service**.

---

## 🔍 Verification & Health Monitoring

Once deployed:
- Open your Render service URL (e.g. `https://udise-scraper.onrender.com/`). You will see `{"status": "healthy"}`.
- Visit `https://udise-scraper.onrender.com/status` to see real-time PIN and school counters.
- Check your Hugging Face dataset [herseiiii/udise-data](https://huggingface.co/datasets/herseiiii/udise-data) — `parquet/pin_tasks.parquet` and `parquet/schools.parquet` will update continuously as the scraper finishes PINs.
