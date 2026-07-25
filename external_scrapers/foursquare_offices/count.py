import json
import pandas as pd
import plotly.express as px

# File paths
hierarchy_json = "foursquare_true_hierarchy.json"
density_csv = "category_density_report.csv"
output_html = "bangalore_aggregated_lineage.html"

# Load the base taxonomy and counts
with open(hierarchy_json, "r") as f:
    hierarchy_tree = json.load(f)
density_df = pd.read_csv(density_csv)
density_map = dict(zip(density_df['Category'], density_df['Total Listings']))

# This dictionary will store our calculated totals
category_totals = {}

def calculate_recursive_counts(node):
    total = 0
    for cat_id, details in node.items():
        # 1. Start with the local count of this category
        local_count = density_map.get(details["category_name"], 0)
        
        # 2. Add counts from all children (Recursion)
        children_count = 0
        if details.get("subcategories"):
            children_count = calculate_recursive_counts(details["subcategories"])
        
        # 3. Aggregate
        total_for_node = local_count + children_count
        category_totals[cat_id] = total_for_node
        
        # Return total for the parent to use
        total += total_for_node
    return total

# Run the aggregator
calculate_recursive_counts(hierarchy_tree)

# Build the final records for the Treemap
lineage_records = []
def build_records(node, parent_id="ROOT"):
    for cat_id, details in node.items():
        lineage_records.append({
            "id": cat_id,
            "name": details["category_name"],
            "parent": parent_id,
            "value": category_totals.get(cat_id, 0)
        })
        if details.get("subcategories"):
            build_records(details["subcategories"], cat_id)

build_records(hierarchy_tree)
lineage_records.append({"id": "ROOT", "name": "Foursquare Taxonomy", "parent": "", "value": sum(category_totals.values())})

# Plot
df = pd.DataFrame(lineage_records)
fig = px.treemap(df, names='name', parents='parent', ids='id', values='value', 
                 title='Aggregated Category Density (Parent + Child Totals)')
fig.write_html(output_html)
print(f"Success! Aggregated map saved to '{output_html}'.")