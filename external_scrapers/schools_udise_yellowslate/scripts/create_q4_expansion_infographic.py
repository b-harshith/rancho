#!/usr/bin/env python3
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/client_delivery/schools_geocoded_unified_with_campuses.csv"
OUTPUT = ROOT / "data/client_delivery/q4_market_expansion_matrix.png"

CAPACITY = 200
OCCUPANCY = 0.80
EFFECTIVE_CAPACITY = CAPACITY * OCCUPANCY
PENETRATION = [0.01, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25]
EXISTING_DELHI_CAMPUSES = 4

NAVY = "#102A43"
BLUE = "#176B87"
TEAL = "#1B998B"
GOLD = "#D9A441"
PALE = "#EDF5F7"
LIGHT_GOLD = "#FBF4E4"
GRAY = "#52606D"


def number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def money_lakh(value):
    return f"₹{value / 100_000:.2f}L"


def money_crore(value):
    return f"₹{value / 10_000_000:,.1f} Cr"


def display_city(city):
    return {"delhi_ncr": "Delhi NCR", "bangalore": "Bangalore"}.get(city, city.title())


def main():
    with open(INPUT, encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    # Campus-level market: never double-count multiple source entities.
    campuses = {}
    for row in rows:
        campuses.setdefault(row["campus_id"], row)

    city_data = []
    for city in sorted(
        {row["city"] for row in campuses.values()},
        key=lambda c: int(next(r["city_rank_by_q4_count"] for r in rows if r["city"] == c)),
    ):
        q4 = [row for row in campuses.values() if row["city"] == city and row["fee_quartile"] == "Q4"]
        students = sum(number(row["campus_students_grades_2_9"]) for row in q4)
        fee_maxes = [number(row["campus_fee_max"]) for row in q4 if number(row["campus_fee_max"]) > 0]
        tuition = 0
        for row in q4:
            low, high = number(row["campus_fee_min"]), number(row["campus_fee_max"])
            fee = (low + high) / 2 if low and high else high or low
            tuition += number(row["campus_students_grades_2_9"]) * fee
        city_data.append({
            "city": display_city(city), "city_key": city, "q4": len(q4), "students": students,
            "fee_start": min(fee_maxes), "fee_end": max(fee_maxes), "tuition": tuition,
            "campuses": [math.ceil(students * level / EFFECTIVE_CAPACITY) for level in PENETRATION],
        })

    total_q4 = sum(row["q4"] for row in city_data)
    total_students = sum(row["students"] for row in city_data)
    total_tuition = sum(row["tuition"] for row in city_data)
    total_curve = [sum(row["campuses"][i] for row in city_data) for i in range(len(PENETRATION))]
    delhi = next(row for row in city_data if row["city_key"] == "delhi_ncr")
    delhi_current_penetration = EXISTING_DELHI_CAMPUSES * CAPACITY / delhi["students"] * 100
    delhi_new = [max(0, count - EXISTING_DELHI_CAMPUSES) for count in delhi["campuses"]]

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.titleweight": "bold"})
    fig = plt.figure(figsize=(24, 18), dpi=160, facecolor="white")
    gs = GridSpec(22, 24, figure=fig, hspace=1.0, wspace=0.8)

    # Header
    ax = fig.add_subplot(gs[0:2, :]); ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, color=NAVY))
    ax.text(0.025, 0.64, "Q4 SCHOOL MARKET & CAMPUS EXPANSION MATRIX", color="white",
            fontsize=27, fontweight="bold", va="center")
    ax.text(0.025, 0.23,
            "City-specific premium school demand | Grade 2–9 student market | Annual fee economics",
            color="#D9EAF0", fontsize=14, va="center")

    # Assumptions banner
    ax = fig.add_subplot(gs[2:4, :]); ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0.08), 1, 0.84, transform=ax.transAxes, color=PALE))
    assumptions = [
        ("Campus capacity", "200 students"), ("Target occupancy", "80%"),
        ("Effective capacity", "160 students/campus"), ("Existing Delhi footprint", "4 campuses / 800 seats"),
    ]
    for i, (label, value) in enumerate(assumptions):
        x = 0.03 + i * 0.245
        ax.text(x, 0.63, label.upper(), fontsize=10, color=GRAY, fontweight="bold")
        ax.text(x, 0.30, value, fontsize=16, color=NAVY, fontweight="bold")

    # KPI cards
    ax = fig.add_subplot(gs[4:6, :]); ax.axis("off")
    kpis = [
        (f"{total_q4:,}", "Q4 campuses"), (f"{total_students:,.0f}", "target students"),
        (money_crore(total_tuition), "estimated annual tuition"), ("7", "cities"),
    ]
    for i, (value, label) in enumerate(kpis):
        x = 0.01 + i * 0.25
        ax.add_patch(plt.Rectangle((x, 0.06), 0.235, 0.88, transform=ax.transAxes,
                                   facecolor=LIGHT_GOLD if i == 2 else "#F6F9FB", edgecolor="#D6E1E8"))
        ax.text(x + 0.1175, 0.60, value, ha="center", va="center", fontsize=23,
                color=GOLD if i == 2 else NAVY, fontweight="bold", transform=ax.transAxes)
        ax.text(x + 0.1175, 0.27, label.upper(), ha="center", fontsize=10, color=GRAY,
                fontweight="bold", transform=ax.transAxes)

    # Main matrix table
    ax = fig.add_subplot(gs[6:13, :]); ax.axis("off")
    ax.set_title("CITY-WISE Q4 MARKET AND CAMPUSES REQUIRED AT TARGET PENETRATION",
                 loc="left", fontsize=16, color=NAVY, pad=12)
    headers = ["City", "Q4\nschools", "Students", "Q4 annual fee\nbracket", "Annual tuition\nmarket"] + [f"{int(p*100)}%" for p in PENETRATION]
    table_rows = []
    for row in city_data:
        table_rows.append([
            row["city"], f"{row['q4']:,}", f"{row['students']:,.0f}",
            f"{money_lakh(row['fee_start'])}–{money_lakh(row['fee_end'])}", money_crore(row["tuition"]),
            *[f"{value:,}" for value in row["campuses"]],
        ])
    table_rows.append(["TOTAL", f"{total_q4:,}", f"{total_students:,.0f}", "—",
                       money_crore(total_tuition), *[f"{value:,}" for value in total_curve]])
    col_widths = [0.105, 0.06, 0.08, 0.145, 0.105] + [0.055] * 7
    table = ax.table(cellText=table_rows, colLabels=headers, cellLoc="center", colLoc="center",
                     colWidths=col_widths, bbox=[0, 0.02, 1, 0.92])
    table.auto_set_font_size(False); table.set_fontsize(10.5)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#CFD8E3"); cell.set_linewidth(0.7)
        if r == 0:
            cell.set_facecolor(NAVY); cell.get_text().set_color("white"); cell.get_text().set_fontweight("bold")
        elif r == len(table_rows):
            cell.set_facecolor(LIGHT_GOLD); cell.get_text().set_fontweight("bold"); cell.get_text().set_color(NAVY)
        elif r % 2 == 0:
            cell.set_facecolor("#F7FAFC")
        if c == 0 and r > 0:
            cell.get_text().set_ha("left"); cell.get_text().set_fontweight("bold")
    ax.text(0.76, -0.03, "Campus counts use 160 occupied seats per campus", transform=ax.transAxes,
            ha="center", fontsize=9, color=GRAY, style="italic")

    # Charts
    ax1 = fig.add_subplot(gs[14:19, 0:12])
    names = [row["city"] for row in reversed(city_data)]
    values = [row["students"] for row in reversed(city_data)]
    bars = ax1.barh(names, values, color=TEAL)
    ax1.set_title("Q4 ADDRESSABLE STUDENTS", loc="left", fontsize=15, color=NAVY)
    ax1.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
    ax1.grid(axis="x", alpha=0.2); ax1.set_axisbelow(True)
    ax1.spines[["top", "right", "left"]].set_visible(False)
    for bar, value in zip(bars, values):
        ax1.text(value + max(values) * 0.01, bar.get_y() + bar.get_height()/2, f"{value:,.0f}", va="center", fontsize=9)

    ax2 = fig.add_subplot(gs[14:19, 13:24])
    pct = [int(x * 100) for x in PENETRATION]
    ax2.plot(pct, total_curve, color=BLUE, marker="o", linewidth=3, label="All cities")
    ax2.plot(pct, delhi["campuses"], color=GOLD, marker="o", linewidth=3, label="Delhi total")
    ax2.plot(pct, delhi_new, color="#C84630", marker="o", linestyle="--", linewidth=2, label="Delhi additional")
    ax2.set_title("CAMPUS EXPANSION CURVE", loc="left", fontsize=15, color=NAVY)
    ax2.set_xlabel("Target market penetration"); ax2.set_ylabel("Campuses required")
    ax2.set_xticks(pct); ax2.set_xticklabels([f"{x}%" for x in pct])
    ax2.grid(alpha=0.2); ax2.legend(frameon=False, loc="upper left")
    ax2.spines[["top", "right"]].set_visible(False)

    # Delhi callout and notes
    ax = fig.add_subplot(gs[19:22, :]); ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0.38), 1, 0.58, transform=ax.transAxes, facecolor="#FFF7E6", edgecolor="#E8C36A"))
    ax.text(0.02, 0.79, "DELHI BASELINE & EXPANSION", fontsize=12, fontweight="bold", color=NAVY)
    ax.text(0.02, 0.57,
            f"Current implied Q4 penetration: {delhi_current_penetration:.2f}%  |  Additional campuses: " +
            "  •  ".join(f"{int(p*100)}% → {n}" for p, n in zip(PENETRATION, delhi_new)),
            fontsize=11, color=NAVY)
    ax.text(0.01, 0.18,
            "Method: Q4 is calculated separately within each city using annual fee_max. Fee bracket shows the lowest and highest fee_max in Q4. "
            "Tuition market = annual advertised fee midpoint × Grade 2–9 enrollment. Campus counts are rounded up.",
            fontsize=9, color=GRAY, wrap=True)
    ax.text(0.01, 0.02,
            "Directional planning model: enrollment and advertised fees may contain estimates or missing records; validate local catchments before site commitment.",
            fontsize=8.5, color="#7B8794", style="italic")

    fig.savefig(OUTPUT, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {OUTPUT}")
    print(f"Q4 fee starts/ends by city: " + "; ".join(
        f"{row['city']} {money_lakh(row['fee_start'])}–{money_lakh(row['fee_end'])}" for row in city_data))


if __name__ == "__main__":
    main()
