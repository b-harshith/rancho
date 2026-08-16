from __future__ import annotations

import os
import shutil
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("UDISE_DB", ROOT / "data/runtime/udise_data.sqlite3"))
RECIPIENT = os.environ.get("RECIPIENT_EMAIL", "bejjankiharshith1234@gmail.com")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

HF_TOKEN = os.environ.get("HF_TOKEN", "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")
HF_REPO = os.environ.get("HF_REPO", "herseiiii/udise-data")

def ensure_db_exists() -> bool:
    if DB_PATH.exists() and DB_PATH.stat().st_size > 100_000:
        return True
    if HF_TOKEN and HF_REPO:
        try:
            print(f"Downloading database from HF Dataset ({HF_REPO}) for report...")
            downloaded = hf_hub_download(
                repo_id=HF_REPO,
                filename="udise_data.sqlite3",
                repo_type="dataset",
                token=HF_TOKEN
            )
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(downloaded, DB_PATH)
            return True
        except Exception as e:
            print(f"Could not download database from HF: {e}")
            return DB_PATH.exists()
    return DB_PATH.exists()

def get_stats() -> dict[str, Any]:
    if not ensure_db_exists():
        return {}
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # PIN status counts
    pins = cursor.execute(
        "SELECT status, COUNT(*) as cnt FROM pin_tasks GROUP BY status"
    ).fetchall()
    pin_counts = {row["status"]: row["cnt"] for row in pins}
    total_pins = sum(pin_counts.values()) or 19312
    completed_pins = pin_counts.get("completed", 0)
    failed_pins = pin_counts.get("failed", 0)
    pending_pins = total_pins - completed_pins - failed_pins
    
    # School stats
    schools = cursor.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status IN ('completed','partial') THEN 1 ELSE 0 END) as completed "
        "FROM schools"
    ).fetchone()
    total_schools = schools["total"] or 0
    completed_schools = schools["completed"] or 0
    
    # Network responses
    responses = cursor.execute("SELECT COUNT(*) FROM network_responses").fetchone()[0] or 0
    
    # Recent schools
    recent_schools = cursor.execute(
        "SELECT school_name, pincode, udise_code, status, updated_at "
        "FROM schools WHERE school_name IS NOT NULL ORDER BY updated_at DESC LIMIT 8"
    ).fetchall()
    
    conn.close()
    
    pct = round((completed_pins / total_pins) * 100, 2)
    
    return {
        "total_pins": total_pins,
        "completed_pins": completed_pins,
        "failed_pins": failed_pins,
        "pending_pins": pending_pins,
        "pct": pct,
        "total_schools": total_schools,
        "completed_schools": completed_schools,
        "responses": responses,
        "recent_schools": [dict(r) for r in recent_schools],
    }

def generate_html(stats: dict[str, Any]) -> str:
    pct = stats.get("pct", 0)
    recent_rows = ""
    for s in stats.get("recent_schools", []):
        recent_rows += f"""
        <tr>
            <td style="padding: 8px; border-bottom: 1px solid #eee;">{s.get('school_name', 'N/A')}</td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">{s.get('pincode', 'N/A')}</td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;"><code>{s.get('udise_code', 'N/A')}</code></td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">
                <span style="background: #e6fffa; color: #047857; padding: 3px 8px; border-radius: 12px; font-size: 12px; font-weight: bold;">{s.get('status', 'N/A')}</span>
            </td>
        </tr>
        """
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px;">
        <div style="background: #ffffff; max-width: 650px; margin: 0 auto; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); padding: 30px; color: #333;">
            <div style="text-align: center; border-bottom: 2px solid #eef2f5; padding-bottom: 20px;">
                <h2 style="color: #1a202c; margin: 0; font-size: 24px;">📊 UDISE+ Scraper Progress Report</h2>
                <p style="color: #718096; margin: 5px 0 0 0; font-size: 14px;">Automated 6-Hour Cloud Update</p>
            </div>
            
            <div style="margin-top: 25px;">
                <div style="display: flex; justify-content: space-between; font-size: 14px; font-weight: bold; color: #4a5568;">
                    <span>Overall PIN Completion</span>
                    <span>{pct}% ({stats.get('completed_pins', 0)} / {stats.get('total_pins', 19312)} PINs)</span>
                </div>
                <div style="background: #edf2f7; border-radius: 10px; height: 20px; overflow: hidden; margin: 10px 0 20px 0;">
                    <div style="background: linear-gradient(90deg, #3182ce, #63b3ed); height: 100%; width: {pct}%;"></div>
                </div>
            </div>

            <div style="display: table; width: 100%; table-layout: fixed; margin: 20px 0;">
                <div style="display: table-row;">
                    <div style="display: table-cell; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; width: 48%;">
                        <strong style="display: block; font-size: 22px; color: #2d3748;">{stats.get('completed_pins', 0):,}</strong>
                        <span style="font-size: 11px; color: #718096; text-transform: uppercase;">Completed PIN Codes</span>
                    </div>
                    <div style="display: table-cell; width: 4%;"></div>
                    <div style="display: table-cell; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; width: 48%;">
                        <strong style="display: block; font-size: 22px; color: #e53e3e;">{stats.get('failed_pins', 0):,}</strong>
                        <span style="font-size: 11px; color: #718096; text-transform: uppercase;">Failed PIN Attempts</span>
                    </div>
                </div>
            </div>

            <div style="display: table; width: 100%; table-layout: fixed; margin-bottom: 20px;">
                <div style="display: table-row;">
                    <div style="display: table-cell; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; width: 48%;">
                        <strong style="display: block; font-size: 22px; color: #2d3748;">{stats.get('total_schools', 0):,}</strong>
                        <span style="font-size: 11px; color: #718096; text-transform: uppercase;">Discovered Schools</span>
                    </div>
                    <div style="display: table-cell; width: 4%;"></div>
                    <div style="display: table-cell; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; width: 48%;">
                        <strong style="display: block; font-size: 22px; color: #38a169;">{stats.get('completed_schools', 0):,}</strong>
                        <span style="font-size: 11px; color: #718096; text-transform: uppercase;">Fully Scraped Schools</span>
                    </div>
                </div>
            </div>

            <div style="background: #ebf8ff; border: 1px solid #bee3f8; border-radius: 8px; padding: 15px; text-align: center; margin-bottom: 25px;">
                <strong style="display: block; font-size: 24px; color: #2b6cb0;">{stats.get('responses', 0):,}</strong>
                <span style="font-size: 11px; color: #4a5568; text-transform: uppercase;">Captured JSON Network API Responses</span>
            </div>

            <h3 style="font-size: 16px; color: #2d3748; margin-bottom: 10px;">🏫 Recently Scraped Schools</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background: #edf2f7; color: #4a5568;">
                        <th style="padding: 8px; text-align: left;">School Name</th>
                        <th style="padding: 8px; text-align: center;">PIN</th>
                        <th style="padding: 8px; text-align: center;">UDISE Code</th>
                        <th style="padding: 8px; text-align: center;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {recent_rows if recent_rows else '<tr><td colspan="4" style="text-align:center; padding:15px; color:#718096;">No school records parsed yet.</td></tr>'}
                </tbody>
            </table>

            <div style="text-align: center; margin-top: 30px; font-size: 12px; color: #a0aec0;">
                <p>Sent automatically by GitHub Actions Cloud Worker.<br>Dataset Repository: <code>herseiiii/udise-data</code></p>
            </div>
        </div>
    </body>
    </html>
    """

def send_email() -> None:
    stats = get_stats()
    if not stats:
        print("No database stats available for report.")
        return
        
    html_content = generate_html(stats)
    subject = f"UDISE+ Scraper Update: {stats['completed_pins']} PINs Done ({stats['pct']}%) - {stats['total_schools']} Schools"
    
    print("\n--- EMAIL PROGRESS SUMMARY ---")
    print(f"Recipient: {RECIPIENT}")
    print(f"Subject: {subject}")
    print(f"PIN Completion: {stats['completed_pins']} / {stats['total_pins']} ({stats['pct']}%)")
    print(f"Schools Extracted: {stats['total_schools']:,} (Processed: {stats['completed_schools']:,})")
    print(f"Captured Network API Responses: {stats['responses']:,}")
    
    if not SMTP_USER or not SMTP_PASS:
        print("\n⚠️ SMTP_USER or SMTP_PASS environment variables are not configured.")
        print("To send emails to your inbox automatically:")
        print("1. Get a Gmail App Password (or SMTP credentials).")
        print("2. Add GitHub Repository Secrets: SMTP_USER and SMTP_PASS.")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = RECIPIENT
        msg.attach(MIMEText(html_content, "html"))
        
        print(f"Connecting to SMTP server {SMTP_HOST}:{SMTP_PORT}...")
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, RECIPIENT, msg.as_string())
        server.quit()
        print("✅ Email notification successfully delivered!")
    except Exception as e:
        print(f"❌ Failed to send email via SMTP: {e}")

if __name__ == "__main__":
    send_email()
