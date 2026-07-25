import os
import pandas as pd
import json

csv_filename = "foursquare_os_categories.csv"
json_filename = "foursquare_true_hierarchy.json"

if not os.path.exists(csv_filename):
    print(f"Error: '{csv_filename}' not found.")
else:
    print(f"Reading '{csv_filename}'...")
    df = pd.read_csv(csv_filename)
    
    hierarchy_tree = {}

    print("Building the hierarchical tree with level numbers...")
    
    for index, row in df.iterrows():
        current_level = hierarchy_tree
        
        for i in range(1, 7):
            id_col = f'level{i}_category_id'
            name_col = f'level{i}_category_name'
            
            # If this level is empty for this row, stop going deeper
            if pd.isna(row.get(id_col)):
                break 
                
            cat_id = str(row[id_col])
            cat_name = str(row[name_col])
            
            # Add the category if it hasn't been added yet
            if cat_id not in current_level:
                current_level[cat_id] = {
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "level": i,               # ADDED: Explicitly states the level number
                    "subcategories": {} 
                }
            
            # Move down into the subcategories for the next iteration
            current_level = current_level[cat_id]["subcategories"]

    # ADDED: Replace empty {} with actual `null` values to clearly show no further levels exist
    def set_empty_to_null(node):
        for key, value in node.items():
            if not value["subcategories"]:
                value["subcategories"] = None # 'None' in Python becomes 'null' in JSON
            else:
                set_empty_to_null(value["subcategories"])
                
    set_empty_to_null(hierarchy_tree)

    # Save to JSON
    with open(json_filename, "w") as f:
        json.dump(hierarchy_tree, f, indent=4)
        
    print(f"Success! Updated hierarchical tree saved to '{json_filename}'.")