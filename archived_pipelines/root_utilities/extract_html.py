import sqlite3
import re

found = False
for db_file in ['logs_2.sqlite', 'state_5.sqlite', 'memories_1.sqlite']:
    try:
        conn = sqlite3.connect(f'/Users/malleswararao/.codex/{db_file}')
        cursor = conn.cursor()
        
        # Get all text columns in all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        
        for table in tables:
            try:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cursor.fetchall() if r[2] in ('TEXT', 'VARCHAR')]
                
                if cols:
                    query = f"SELECT {','.join(cols)} FROM {table}"
                    cursor.execute(query)
                    for row in cursor.fetchall():
                        for cell in row:
                            if cell and isinstance(cell, str) and '<!-- Navigation Tabs -->' in cell:
                                print(f"--- FOUND IN {db_file} -> {table} ---")
                                # Extract from Navigation Tabs to </aside>
                                match = re.search(r'<!-- Navigation Tabs -->.*?</aside>', cell, re.DOTALL)
                                if match:
                                    print("MATCH FOUND:")
                                    print(match.group(0)[:500] + "...\n" + match.group(0)[-200:])
                                    found = True
                                    with open('recovered_sidebar.html', 'w') as out:
                                        out.write(match.group(0))
            except Exception as e:
                pass
    except Exception as e:
        pass

if not found:
    print("Not found in SQLite databases.")

