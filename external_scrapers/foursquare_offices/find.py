import os
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# Setting your Hugging Face token to bypass authentication prompts
os.environ["HF_TOKEN"] = "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"

csv_filename = "foursquare_os_categories.csv"

if not os.path.exists(csv_filename):
    print(f"Error: '{csv_filename}' not found.")
else:
    print("Loading data and AI embedding model (this may take a moment on the first run)...")
    df = pd.read_csv(csv_filename)
    
    # We use a fast, lightweight model perfect for semantic similarity
    model = SentenceTransformer('all-MiniLM-L6-v2')

    print("Extracting Parent-Child relationships...")
    audit_records = []

    # Loop through the data to pair the lowest level child with its Level 1 Parent
    for index, row in df.iterrows():
        root_parent = str(row['level1_category_name'])
        
        # Find the deepest category name in this specific row
        deepest_child = None
        for i in range(6, 1, -1): # Count backward from Level 6 to Level 2
            col_name = f'level{i}_category_name'
            if not pd.isna(row.get(col_name)):
                deepest_child = str(row[col_name])
                break
                
        # If we have a valid child and parent, save them for comparison
        if deepest_child and root_parent != 'nan':
            audit_records.append({
                "Root Parent": root_parent,
                "Deepest Child": deepest_child
            })

    # Convert to DataFrame and drop duplicates (so we only test unique pairs once)
    pairs_df = pd.DataFrame(audit_records).drop_duplicates()
    
    print(f"Analyzing {len(pairs_df)} unique relationships for semantic anomalies...")

    # Generate vector embeddings for all parents and all children
    parent_embeddings = model.encode(pairs_df['Root Parent'].tolist())
    child_embeddings = model.encode(pairs_df['Deepest Child'].tolist())

    # Calculate Cosine Similarity between each parent-child pair
    similarities = []
    for i in range(len(pairs_df)):
        # Reshape is required by scikit-learn for single vector comparisons
        parent_vec = parent_embeddings[i].reshape(1, -1)
        child_vec = child_embeddings[i].reshape(1, -1)
        
        # Calculate score (1.0 is identical, 0.0 is completely unrelated)
        score = cosine_similarity(parent_vec, child_vec)[0][0]
        similarities.append(score)

    pairs_df['Similarity Score'] = similarities

    # Sort by the LOWEST scores to find the worst misclassifications
    flagged_df = pairs_df.sort_values(by='Similarity Score', ascending=True)

    print("\n🚨 TOP 15 POTENTIAL MISCLASSIFICATIONS (Lowest Similarity Scores) 🚨")
    print("-" * 75)
    print(f"{'Root Parent':<35} | {'Child Category':<25} | {'Score'}")
    print("-" * 75)
    
    for index, row in flagged_df.head(15).iterrows():
        parent = row['Root Parent'][:33]
        child = row['Deepest Child'][:23]
        score = row['Similarity Score']
        print(f"{parent:<35} | {child:<25} | {score:.3f}")

    # Export the full audit to review manually
    flagged_df.to_csv("taxonomy_audit_results.csv", index=False)
    print("\nFull audit report saved to 'taxonomy_audit_results.csv'")