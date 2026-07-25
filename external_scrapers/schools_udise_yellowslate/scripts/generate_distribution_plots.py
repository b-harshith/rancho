import json
import os
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set style
sns.set_theme(style="whitegrid")
plt.rcParams.update({
    'font.size': 11,
    'axes.labelsize': 12,
    'axes.titlesize': 14,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'figure.titlesize': 16,
    'font.family': 'sans-serif'
})

def main():
    # Load data
    with open("data/output/schools_analysis_classified.json") as f:
        data = json.load(f)

    schools = data["schools"]
    records = []
    for s in schools:
        total_students = (s.get("enrollment") or {}).get("total_students")
        fee_info = s.get("fee_information") or {}
        avg_fee = fee_info.get("average_annual_fee")
        records.append({
            "udise_code": s.get("udise_code"),
            "total_students": total_students if total_students is not None else 0,
            "average_annual_fee": avg_fee,
            "fee_group": s.get("analysis_dimensions", {}).get("fee_group")
        })

    df = pd.DataFrame(records)

    # 1. Enrollment Quartiles
    df['enrollment_q'] = pd.qcut(df['total_students'], q=4, labels=['Q1', 'Q2', 'Q3', 'Q4'])
    enrollment_ranges = df.groupby('enrollment_q')['total_students'].agg(['min', 'max'])
    
    enrollment_summary = df.groupby('enrollment_q').agg(
        schools_count=('udise_code', 'count'),
        total_students=('total_students', 'sum')
    ).reset_index()

    # 2. Fee Quartiles (for schools that have fee data)
    fee_df = df[df['average_annual_fee'].notnull()].copy()
    fee_df['fee_q'] = pd.qcut(fee_df['average_annual_fee'], q=4, labels=['Q1', 'Q2', 'Q3', 'Q4'])
    fee_ranges = fee_df.groupby('fee_q')['average_annual_fee'].agg(['min', 'max'])
    
    fee_summary = fee_df.groupby('fee_q').agg(
        schools_count=('udise_code', 'count'),
        total_students=('total_students', 'sum')
    ).reset_index()

    # Define color scheme
    color_schools = '#5B21B6' # Indigo/purple
    color_students = '#059669' # Emerald/green

    # Create figure with 2 subplots side-by-side
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5))
    
    # --- PLOT 1: ENROLLMENT QUARTILES ---
    ax1 = axes[0]
    ax1_twin = ax1.twinx()
    
    x = np.arange(4)
    width = 0.35
    
    # Plot bars
    bar1 = ax1.bar(x - width/2, enrollment_summary['schools_count'], width, label='Number of Schools', color=color_schools, alpha=0.85)
    bar2 = ax1_twin.bar(x + width/2, enrollment_summary['total_students'], width, label='Number of Students', color=color_students, alpha=0.85)
    
    # X-axis labels with ranges
    labels = []
    for q in ['Q1', 'Q2', 'Q3', 'Q4']:
        row = enrollment_ranges.loc[q]
        labels.append(f"{q}\n({int(row['min'])}-{int(row['max'])} stds)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    
    ax1.set_title('Enrollment Distribution by Quartiles', pad=15, fontweight='bold')
    ax1.set_xlabel('Enrollment Quartiles (Student Range)')
    ax1.set_ylabel('Number of Schools', color=color_schools, fontweight='bold')
    ax1_twin.set_ylabel('Number of Students', color=color_students, fontweight='bold')
    
    ax1.tick_params(axis='y', labelcolor=color_schools)
    ax1_twin.tick_params(axis='y', labelcolor=color_students)
    
    # Add values on top of bars
    for rect in bar1:
        height = rect.get_height()
        ax1.annotate(f'{int(height)}',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=9, fontweight='semibold')
                    
    for rect in bar2:
        height = rect.get_height()
        ax1_twin.annotate(f'{int(height):,}',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=9, fontweight='semibold')
    
    # --- PLOT 2: FEE QUARTILES ---
    ax2 = axes[1]
    ax2_twin = ax2.twinx()
    
    bar3 = ax2.bar(x - width/2, fee_summary['schools_count'], width, label='Number of Schools', color=color_schools, alpha=0.85)
    bar4 = ax2_twin.bar(x + width/2, fee_summary['total_students'], width, label='Number of Students', color=color_students, alpha=0.85)
    
    # X-axis labels with ranges
    fee_labels = []
    for q in ['Q1', 'Q2', 'Q3', 'Q4']:
        row = fee_ranges.loc[q]
        fee_labels.append(f"{q}\n(Rs. {int(row['min'])/1000:.1f}k-Rs. {int(row['max'])/1000:.1f}k)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(fee_labels)
    
    ax2.set_title('Fee Distribution by Quartiles\n(for 1,032 schools with fee data)', pad=15, fontweight='bold')
    ax2.set_xlabel('Annual Fee Quartiles (Fee Range)')
    ax2.set_ylabel('Number of Schools', color=color_schools, fontweight='bold')
    ax2_twin.set_ylabel('Number of Students', color=color_students, fontweight='bold')
    
    ax2.tick_params(axis='y', labelcolor=color_schools)
    ax2_twin.tick_params(axis='y', labelcolor=color_students)
    
    # Add values on top of bars
    for rect in bar3:
        height = rect.get_height()
        ax2.annotate(f'{int(height)}',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=9, fontweight='semibold')
                    
    for rect in bar4:
        height = rect.get_height()
        ax2_twin.annotate(f'{int(height):,}',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=9, fontweight='semibold')

    # Add a global title
    fig.suptitle('School and Student Distributions by Enrollment and Fee Quartiles', fontsize=16, fontweight='bold', y=0.98)
    
    plt.tight_layout()
    
    # Save the plot
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    img_path = output_dir / "school_student_quartile_distribution.png"
    plt.savefig(img_path, dpi=300)
    print(f"Plot saved successfully to: {img_path.resolve()}")
    
    # Also let's save the data summary as JSON/text for reference
    summary_data = {
        "enrollment_quartiles": {
            "Q1": {"range": f"0 - {int(enrollment_ranges.loc['Q1', 'max'])}", "schools": int(enrollment_summary.loc[0, 'schools_count']), "students": int(enrollment_summary.loc[0, 'total_students'])},
            "Q2": {"range": f"{int(enrollment_ranges.loc['Q2', 'min'])} - {int(enrollment_ranges.loc['Q2', 'max'])}", "schools": int(enrollment_summary.loc[1, 'schools_count']), "students": int(enrollment_summary.loc[1, 'total_students'])},
            "Q3": {"range": f"{int(enrollment_ranges.loc['Q3', 'min'])} - {int(enrollment_ranges.loc['Q3', 'max'])}", "schools": int(enrollment_summary.loc[2, 'schools_count']), "students": int(enrollment_summary.loc[2, 'total_students'])},
            "Q4": {"range": f"{int(enrollment_ranges.loc['Q4', 'min'])} - {int(enrollment_ranges.loc['Q4', 'max'])}", "schools": int(enrollment_summary.loc[3, 'schools_count']), "students": int(enrollment_summary.loc[3, 'total_students'])},
        },
        "fee_quartiles": {
            "Q1": {"range": f"Rs. {int(fee_ranges.loc['Q1', 'min'])} - Rs. {int(fee_ranges.loc['Q1', 'max'])}", "schools": int(fee_summary.loc[0, 'schools_count']), "students": int(fee_summary.loc[0, 'total_students'])},
            "Q2": {"range": f"Rs. {int(fee_ranges.loc['Q2', 'min'])} - Rs. {int(fee_ranges.loc['Q2', 'max'])}", "schools": int(fee_summary.loc[1, 'schools_count']), "students": int(fee_summary.loc[1, 'total_students'])},
            "Q3": {"range": f"Rs. {int(fee_ranges.loc['Q3', 'min'])} - Rs. {int(fee_ranges.loc['Q3', 'max'])}", "schools": int(fee_summary.loc[2, 'schools_count']), "students": int(fee_summary.loc[2, 'total_students'])},
            "Q4": {"range": f"Rs. {int(fee_ranges.loc['Q4', 'min'])} - Rs. {int(fee_ranges.loc['Q4', 'max'])}", "schools": int(fee_summary.loc[3, 'schools_count']), "students": int(fee_summary.loc[3, 'total_students'])},
        }
    }
    
    with open(output_dir / "quartile_distribution_data.json", "w") as out:
        json.dump(summary_data, out, indent=2)
        
    print(f"Data summary saved to: {output_dir / 'quartile_distribution_data.json'}")

if __name__ == "__main__":
    main()
