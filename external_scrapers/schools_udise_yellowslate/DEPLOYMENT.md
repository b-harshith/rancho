# Deploying UDISE+ Scraper to GitHub Actions (19300 Pincodes - 100% Free)

Hugging Face recently updated their terms and now requires a **PRO subscription** to host Docker/Python Spaces on free hardware. 

To run this scraper completely **free of charge 24/7 without a subscription**, we have configured the scraper to run via **GitHub Actions** (free runner VMs) and store the database in a **Hugging Face Dataset** (free private cloud storage).

---

## How It Works
1. **GitHub Actions**: Runs a headless virtual machine that executes `run_cli_batch.py`, auto-solving CAPTCHAs with EasyOCR. The scraper itself has no overall runtime cutoff.
2. **Persistent Storage**: On startup, it restores the database from your private Hugging Face Dataset repository. Every 30 minutes, it uploads a transaction-safe SQLite checkpoint.
3. **Continuous Execution**: A continuation is queued every hour. If GitHub rotates the hosted runner, interrupted PIN tasks are returned to the queue and the next run resumes them. Overlapping runs are serialized until all 19,300+ PIN codes reach a terminal state.

---

## Step 1: Initialize Your Private Dataset on Hugging Face
Your private dataset repository has already been created and initialized for you at:
`https://huggingface.co/datasets/herseiiii/udise-data`

---

## Step 2: Configure Your GitHub Repository Secrets
To allow GitHub Actions to download and upload the database securely:

1. Push this codebase to a repository on **GitHub** (either Public or Private).
2. Go to your repository page on GitHub.
3. Click on **Settings** -> **Secrets and variables** -> **Actions**.
4. Click **New repository secret**.
5. Add the following secret:
   - **Name**: `HF_TOKEN`
   - **Value**: `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`
6. Click **Add secret**.

---

## Step 3: Trigger the Scraper

1. Go to the **Actions** tab of your repository on GitHub.
2. Under the left sidebar, click **UDISE Scraper Cloud Job**.
3. Click **Run workflow** -> Select branch (e.g., `main`) -> Click the green **Run workflow** button.
4. The scraper will launch in the background. It will run every 6 hours automatically, or you can manually trigger it again whenever you want to check progress.

---

## Monitoring Progress
Since the scraper runs in the background, you can monitor the status of the database and files directly from your Hugging Face dataset page:
`https://huggingface.co/datasets/herseiiii/udise-data`
Look at the history of commits to see the database updates!
