import json
import os
import matplotlib.pyplot as plt
import numpy as np

def main():
    json_path = "data/99acres_bangalore_societies.json"
    with open(json_path, "r", encoding="utf-8") as f:
        societies = json.load(f)
        
    max_prices = []
    for s in societies:
        max_p = s.get("rei", {}).get("sale", {}).get("price", {}).get("max")
        if max_p is not None and max_p > 0:
            max_prices.append(max_p)
            
    if not max_prices:
        print("No valid max prices found to plot.")
        return
        
    prices = np.array(max_prices)
    
    # Calculate quartiles
    q1 = np.percentile(prices, 25)
    q2 = np.percentile(prices, 50)
    q3 = np.percentile(prices, 75)
    p90 = np.percentile(prices, 90)
    
    print(f"Quartiles:")
    print(f" - Q1 (25%): INR {q1:,.2f}")
    print(f" - Q2 (50% / Median): INR {q2:,.2f}")
    print(f" - Q3 (75%): INR {q3:,.2f}")
    print(f" - 90th Percentile: INR {p90:,.2f}")
    
    # Set up matplotlib style (premium dark mode)
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 7), dpi=300)
    
    # Cap values at 8 Crore (80,000,000) for better histogram visualization
    plot_limit = 80000000.0
    capped_prices = np.clip(prices, 0, plot_limit)
    
    # Determine bins (e.g. 50 bins up to 8 Crore)
    bins = np.linspace(0, plot_limit, 55)
    
    # Plot histogram
    n, bins, patches = ax.hist(capped_prices, bins=bins, color='#00d2ff', alpha=0.85, rwidth=0.9, edgecolor='none')
    
    # Color segments based on quartiles
    for patch, bin_left in zip(patches, bins):
        if bin_left >= q3:
            patch.set_facecolor('#ff2e93')  # Q4 (Ultra Premium / Luxury Segment) - Pink/Magenta
        elif bin_left >= q2:
            patch.set_facecolor('#ff8f00')  # Q3 (Super Luxury / Mid-High Segment) - Orange
        elif bin_left >= q1:
            patch.set_facecolor('#00d2ff')  # Q2 (Standard / Mid Segment) - Cyan
        else:
            patch.set_facecolor('#00ff87')  # Q1 (Budget Segment) - Green
            
    # Add vertical lines for Q1, Q2, Q3
    ax.axvline(q1, color='#00ff87', linestyle='--', linewidth=1.5, alpha=0.8)
    ax.axvline(q2, color='#00d2ff', linestyle='-.', linewidth=1.5, alpha=0.8)
    ax.axvline(q3, color='#ff2e93', linestyle=':', linewidth=1.8, alpha=0.8)
    
    # Set x-ticks to display custom quartile ranges and labels
    standard_ticks = [0, 20000000, 40000000, 60000000, 80000000]
    custom_ticks = sorted(list(set(standard_ticks + [q1, q2, q3])))
    
    # Generate labels for each tick
    tick_labels = []
    for t in custom_ticks:
        if t == 0:
            tick_labels.append("0")
        elif t == q1:
            tick_labels.append(f"\nQ1: {q1/10000000:.2f}Cr\n(75.5L)")
        elif t == q2:
            tick_labels.append(f"\nQ2: {q2/10000000:.1f}Cr\n(1.2Cr)")
        elif t == q3:
            tick_labels.append(f"\nQ3: {q3/10000000:.1f}Cr\n(2.1Cr)")
        else:
            tick_labels.append(f"{int(t/10000000)}Cr")
            
    ax.set_xticks(custom_ticks)
    ax.set_xticklabels(tick_labels, fontsize=9, fontweight='bold', color='#999999')
    
    # Specific color highlighting for quartile tick labels (via annotations or drawing text)
    # Highlight ticks on x axis with vertical line label info
    ax.text(q1, ax.get_ylim()[1]*0.9, f" Q1: {q1/10000000:.2f}Cr", color='#00ff87', fontsize=9, fontweight='bold', alpha=0.9)
    ax.text(q2, ax.get_ylim()[1]*0.8, f" Q2 (Median): {q2/10000000:.1f}Cr", color='#00d2ff', fontsize=9, fontweight='bold', alpha=0.9)
    ax.text(q3, ax.get_ylim()[1]*0.7, f" Q3 (Q4 Boundary): {q3/10000000:.1f}Cr", color='#ff2e93', fontsize=9, fontweight='bold', alpha=0.9)
    
    # Title and Labels
    ax.set_title("Maximum Property Price Distribution of Bangalore Societies", fontsize=16, fontweight='bold', pad=25, color='#ffffff')
    ax.set_xlabel("Property Max Purchase Price (INR Crores / Lakhs)", fontsize=11, labelpad=15, color='#cccccc')
    ax.set_ylabel("Number of Societies", fontsize=11, labelpad=10, color='#cccccc')
    
    # Subtitle with metadata
    plt.suptitle(f"Based on 99acres data for {len(prices)} societies. Values > 8Cr are capped at 8Cr for visualization.", 
                 fontsize=10, color='#888888', y=0.93, style='italic')
    
    # Grid and Styling
    ax.grid(True, linestyle=':', alpha=0.15, color='#ffffff')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#444444')
    ax.spines['bottom'].set_color('#444444')
    
    plt.yticks(fontsize=9, color='#999999')
    
    # Save Image in both workspace and artifacts directory
    output_filename = "society_price_distribution.png"
    plt.savefig(output_filename, bbox_inches='tight', dpi=300)
    
    artifact_image_path = "/Users/malleswararao/.gemini/antigravity-ide/brain/5ad9d68c-7c50-4a98-8496-16e26f027f49/society_price_distribution.png"
    plt.savefig(artifact_image_path, bbox_inches='tight', dpi=300)
    
    print("Successfully generated and saved society price distribution graph.")

if __name__ == "__main__":
    main()
