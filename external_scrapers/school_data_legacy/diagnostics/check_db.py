#!/usr/bin/env python3
import sqlite3
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="Check school database schema and stats.")
    parser.add_argument("--city", type=str, default="bangalore", help="Name of the city (e.g. bangalore, delhi)")
    args = parser.parse_args()
    
    city_slug = args.city.lower().strip().replace(' ', '-')
    db_path = f"data/school_scraping_{city_slug}.db"
    
    if not os.path.exists(db_path):
        db_path = "data/school_scraping.db"
        
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return
        
    print(f"Inspecting SQLite database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"Tables found: {', '.join(tables)}")
    
    # Discovery Stats
    if 'schools_discovery' in tables:
        cursor.execute("SELECT COUNT(*) FROM schools_discovery")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT status, COUNT(*) FROM schools_discovery GROUP BY status")
        status_counts = cursor.fetchall()
        
        print("\nTable 'schools_discovery' stats:")
        print(f" - Total discovered: {total}")
        for status, count in status_counts:
            print(f"   * Status '{status}': {count}")
            
    # Detail Stats
    if 'school_details' in tables:
        cursor.execute("SELECT COUNT(*) FROM school_details")
        total_details = cursor.fetchone()[0]
        print(f"\nTable 'school_details' stats:")
        print(f" - Total scraped profiles: {total_details}")
        
        # Print table columns
        cursor.execute("PRAGMA table_info(school_details)")
        cols = cursor.fetchall()
        print("\nColumns in 'school_details':")
        for c in cols:
            print(f" - {c[1]} ({c[2]})")
            
        # Sample School
        cursor.execute("SELECT name, board, url FROM school_details LIMIT 1")
        sample = cursor.fetchone()
        if sample:
            print("\nSample row:")
            print(f" - Name: {sample[0]}")
            print(f" - Board: {sample[1]}")
            print(f" - URL: {sample[2]}")
            
    conn.close()

if __name__ == "__main__":
    main()
