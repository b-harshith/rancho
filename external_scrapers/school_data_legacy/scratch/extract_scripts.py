import re
import json

with open("scratch/practo_search_loaded.html") as f:
    html = f.read()

# Let's search for script tags containing JSON or __INITIAL_STATE__
scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)
print(f"Total script tags in loaded HTML: {len(scripts)}")

for i, script in enumerate(scripts):
    if "__INITIAL_STATE__" in script:
        print(f"Script {i} contains __INITIAL_STATE__! Length: {len(script)}")
        # Let's save it to a file
        with open("scratch/initial_state.js", "w") as sf:
            sf.write(script)
        print("Saved to scratch/initial_state.js")
    
    # Also check other scripts
    if "window.__" in script:
        print(f"Script {i} has window.__...: {script[:200]}")

# Let's also search for JSON-LD or initial data
for i, script in enumerate(scripts):
    if "hospital" in script.lower() and len(script) > 5000:
        print(f"Script {i} matches hospital and length {len(script)}")
        with open(f"scratch/large_script_{i}.js", "w") as sf:
            sf.write(script)
