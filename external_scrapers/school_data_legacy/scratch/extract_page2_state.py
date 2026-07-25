import re
import json

with open("scratch/page2_debug.html") as f:
    html = f.read()

scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)
print(f"Total script tags in page 2: {len(scripts)}")

found = False
for i, script in enumerate(scripts):
    if "__REDUX_STATE__" in script:
        found = True
        print(f"Script {i} contains __REDUX_STATE__! Length: {len(script)}")
        prefix = "window.__REDUX_STATE__="
        idx = script.find(prefix)
        if idx != -1:
            json_part = script[idx + len(prefix):].strip()
            if json_part.endswith(";"):
                json_part = json_part[:-1].strip()
            
            try:
                state_json = json.loads(json_part)
                print("Successfully parsed JSON!")
                print("Root Keys:", list(state_json.keys()))
                
                # Check establishments
                est = state_json.get("establishments", {})
                print("est keys:", list(est.keys()))
                for k in est.keys():
                    v = est[k]
                    if isinstance(v, dict):
                        print(f"  est.{k} keys: {list(v.keys())}")
                        if "hospitals" in v:
                            print(f"    est.{k}.hospitals keys: {list(v['hospitals'].keys())}")
                            print(f"    est.{k}.hospitals.entities len: {len(v['hospitals'].get('entities', {}))}")
                        if "clinics" in v:
                            print(f"    est.{k}.clinics.entities len: {len(v['clinics'].get('entities', {}))}")
                
                with open("scratch/page2_state.json", "w") as jf:
                    json.dump(state_json, jf, indent=2)
                print("Saved page 2 redux state to scratch/page2_state.json")
            except Exception as e:
                print("Error parsing JSON:", e)
        else:
            print("Found __REDUX_STATE__ in script but not the prefix")

if not found:
    print("Could not find any script tag containing __REDUX_STATE__")
