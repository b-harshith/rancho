import re
import json

with open("scratch/practo_search_loaded.html") as f:
    html = f.read()

scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)

for i, script in enumerate(scripts):
    if "__REDUX_STATE__" in script:
        print(f"Script {i} contains __REDUX_STATE__! Length: {len(script)}")
        # Let's clean the script content
        # It should start with window.__REDUX_STATE__=
        prefix = "window.__REDUX_STATE__="
        idx = script.find(prefix)
        if idx != -1:
            json_part = script[idx + len(prefix):].strip()
            # If it ends with semicolon, remove it
            if json_part.endswith(";"):
                json_part = json_part[:-1].strip()
            
            try:
                state_json = json.loads(json_part)
                print("Successfully parsed JSON!")
                print("Root Keys:", list(state_json.keys()))
                
                with open("scratch/redux_state.json", "w") as jf:
                    json.dump(state_json, jf, indent=2)
                print("Saved to scratch/redux_state.json")
            except Exception as e:
                print("Error parsing JSON:", e)
                # Let's write the first 1000 characters of json_part to see what's wrong
                print("First 200 chars of json_part:", json_part[:200])
                print("Last 200 chars of json_part:", json_part[-200:])
