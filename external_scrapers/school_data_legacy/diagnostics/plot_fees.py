#!/usr/bin/env python3
import json
import os
import argparse
import matplotlib.pyplot as plt
import numpy as np

def main():
    parser = argparse.ArgumentParser(description="Plot distribution of maximum annual school fees.")
    parser.add_argument("--city", type=str, default="bangalore", help="Name of the city (e.g. bangalore, delhi)")
    args = parser.parse_args()
    
    city_slug = args.city.lower().strip().replace(' ', '-')
    json_path = f"data/school_averages_summary_{city_slug}.json"
    
    if not os.path.exists(json_path):
        json_path = "data/school_averages_summary.json"
        
    if not os.path.exists(json_path):
        print(f"Error: Summary JSON file not found at {json_path}")
        return
        
    print(f"Loading data from {json_path}...")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # Extract fees, filter out NA or None values
    fees = []
    for s in data:
        fee = s.get("Average Fee (Annual)")
        if fee != "NA" and fee is not None:
            try:
                fees.append(float(fee))
            except ValueError:
                pass
                
    if not fees:
        print("No valid fee details found in the dataset to plot.")
        return
        
    print(f"Found {len(fees)} schools with valid fee details.")
    fees = np.array(fees)
    
    # Statistics
    mean_fee = np.mean(fees)
    median_fee = np.median(fees)
    p90 = np.percentile(fees, 90)
    p95 = np.percentile(fees, 95)
    
    print(f"Fee stats:")
    print(f" - Mean: ₹{mean_fee:,.2f}")
    print(f" - Median: ₹{median_fee:,.2f}")
    print(f" - 90th percentile: ₹{p90:,.2f}")
    print(f" - 95th percentile: ₹{p95:,.2f}")
    print(f" - Min: ₹{np.min(fees):,.2f}")
    print(f" - Max: ₹{np.max(fees):,.2f}")

    # Set up matplotlib style (sleek, premium dark style)
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 7), dpi=300)
    
    # Filter extremely large outliers for better visual scaling in the histogram (e.g. cap at 5L for the plot)
    # Highlight capped values in the title/subtitle
    plot_limit = 500000
    capped_fees = np.clip(fees, 0, plot_limit)
    
    # Determine bins (e.g. 50 bins up to 5L)
    bins = np.linspace(0, plot_limit, 50)
    
    # Plot histogram
    n, bins, patches = ax.hist(capped_fees, bins=bins, color='#00d2ff', alpha=0.85, rwidth=0.9, edgecolor='none')
    
    # Smooth gradient colors for bars based on fee range
    for patch, bin_left in zip(patches, bins):
        if bin_left >= 300000:
            patch.set_facecolor('#ff2e93')  # Ultra high fee (Magenta)
        elif bin_left >= 150000:
            patch.set_facecolor('#ff8f00')  # High fee (Orange)
        elif bin_left >= 50000:
            patch.set_facecolor('#00d2ff')  # Mid fee (Cyan)
        else:
            patch.set_facecolor('#00ff87')  # Budget/Low fee (Green)
            
    # Draw stats lines
    ax.axvline(mean_fee, color='#ffffff', linestyle='--', linewidth=1.5, alpha=0.8, label=f'Mean: ₹{mean_fee/1000:.1f}k')
    ax.axvline(median_fee, color='#00ff87', linestyle='-.', linewidth=1.5, alpha=0.8, label=f'Median: ₹{median_fee/1000:.1f}k')
    ax.axvline(p90, color='#ff8f00', linestyle=':', linewidth=1.5, alpha=0.8, label=f'90th %ile: ₹{p90/1000:.1f}k')
    
    # Formatting labels and grid
    ax.set_title(f"Maximum Annual School Fee Distribution in {args.city.capitalize()}", fontsize=18, fontweight='bold', pad=20, color='#ffffff')
    ax.set_xlabel("Maximum Annual Fee (₹ INR)", fontsize=12, labelpad=10, color='#cccccc')
    ax.set_ylabel("Number of Schools", fontsize=12, labelpad=10, color='#cccccc')
    
    # Set x-ticks to display cleaner formatted values (e.g., 50k, 1L, etc.)
    ax.set_xticks(np.arange(0, plot_limit + 50000, 50000))
    ax.set_xticklabels([f"0" if x == 0 else f"{int(x/100000)}L" if x >= 100000 else f"{int(x/1000)}k" for x in ax.get_xticks()], fontsize=10, color='#999999')
    
    # Clean y axis ticks
    plt.yticks(fontsize=10, color='#999999')
    
    # Grid details
    ax.grid(True, linestyle=':', alpha=0.2, color='#ffffff')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#444444')
    ax.spines['bottom'].set_color('#444444')
    
    # Add subtitle with context information
    plt.suptitle(f"Based on {len(fees)} schools with fee data. (Values > 5L capped at 5L for display)", 
                 fontsize=10, color='#888888', y=0.92, style='italic')
                 
    # Legend
    legend = ax.legend(loc='upper right', framealpha=0.2, edgecolor='#ffffff', fontsize=10)
    plt.setp(legend.get_texts(), color='#ffffff')
    
    # Save image
    output_filename = f"school_fees_distribution_{city_slug}.png"
    plt.savefig(output_filename, bbox_inches='tight', dpi=300)
    print(f"Successfully saved distribution graph as: {output_filename}")
    
    # Save a generic copy too
    plt.savefig("school_fees_distribution.png", bbox_inches='tight', dpi=300)
    
if __name__ == "__main__":
    main()
