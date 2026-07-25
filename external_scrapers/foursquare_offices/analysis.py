import json
import os
import pandas as pd
import plotly.express as px

json_filename = "foursquare_true_hierarchy.json"
html_filename = "foursquare_lineage_map.html"

if not os.path.exists(json_filename):
    print(f"Error: Could not find '{json_filename}'.")
else:
    print("Loading data and calculating relationships...")
    with open(json_filename, "r") as f:
        hierarchy_tree = json.load(f)

    # We need to flatten the JSON into a list of exact relationships for the visualizer
    lineage_records = []

    def extract_relationships(node, parent_id="ROOT"):
        if not node:
            return
            
        for cat_id, details in node.items():
            lineage_records.append({
                "id": cat_id,
                "name": details["category_name"],
                "parent": parent_id
            })
            
            # If there are children, dig deeper and pass the current ID as their parent
            if details.get("subcategories"):
                extract_relationships(details["subcategories"], cat_id)

    # Start the extraction
    extract_relationships(hierarchy_tree)

    # Add a master "Root" node so all Level 1 categories connect back to a single center point
    lineage_records.append({
        "id": "ROOT",
        "name": "Foursquare Taxonomy",
        "parent": ""
    })

    # Convert the records to a Pandas DataFrame
    df = pd.DataFrame(lineage_records)

    print("Generating the interactive visual map...")
    
    # Create an interactive Treemap (a highly visual, clickable lineage map)
    fig = px.treemap(
        df,
        names='name',
        parents='parent',
        ids='id',
        title='Foursquare Category Lineage Map (Click a category to zoom in!)',
        color_discrete_sequence=px.colors.qualitative.Pastel
    )

    # Improve the visual layout
    fig.update_traces(root_color="lightgrey")
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))

    # Save it as an interactive web page
    fig.write_html(html_filename)
    
    print(f"Success! Open '{html_filename}' in your web browser (Chrome, Safari, Edge) to explore.")