#!/usr/bin/env python3
"""Create a client-shareable PDF from PREMIUM_REGEXES."""

import ast
import datetime as dt
import re
import json
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/fee_classification_udise.py"
PREDICTIONS_PATH = ROOT / "output/fee_classification_predictions_all_udise.csv"
LABELED_PATH = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
BANGALORE_PATH = Path(
    "/Users/malleswararao/Desktop/BangaloreRancho/"
    "web_platform_vercel_exact_latest/src/public/data/schools.json"
)
OUT_DIR = ROOT / "output/pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PDF = OUT_DIR / "premium_school_chain_detection_list.pdf"


ACRONYMS = {
    "dps": "DPS",
    "nps": "NPS",
    "tisb": "TISB",
    "jbcn": "JBCN",
    "gd": "GD",
    "dy": "DY",
    "kr": "KR",
    "rbk": "RBK",
    "hdfc": "HDFC",
    "hfs": "HFS",
    "psbb": "PSBB",
    "dpsg": "DPSG",
    "giis": "GIIS",
    "uwc": "UWC",
    "ib": "IB",
    "igcse": "IGCSE",
    "cisce": "CISCE",
    "icse": "ICSE",
    "cbse": "CBSE",
    "intl": "International",
    "avm": "AVM",
    "spv": "SPV",
    "nafl": "NAFL",
    "bgs": "BGS",
}


def display_name(key: str) -> str:
    words = re.split(r"(\s+|-)", key.strip())
    out = []
    for w in words:
        low = w.lower()
        if not w.strip():
            out.append(w)
        elif low in ACRONYMS:
            out.append(ACRONYMS[low])
        elif len(w) <= 2 and low in {"st", "fr"}:
            out.append(low.title() + ".")
        else:
            out.append(w[:1].upper() + w[1:])
    return "".join(out)


def extract_premium_regexes():
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PREMIUM_REGEXES":
                    rows = []
                    for key_node, val_node in zip(node.value.keys, node.value.values):
                        key = ast.literal_eval(key_node)
                        pattern = ""
                        if isinstance(val_node, ast.Call) and getattr(val_node.func, "attr", "") == "compile":
                            pattern = ast.literal_eval(val_node.args[0])
                        rows.append({
                            "key": key,
                            "proper_name": display_name(key),
                            "pattern": pattern,
                            "regex": re.compile(pattern, re.I),
                        })
                    return rows
    raise RuntimeError("PREMIUM_REGEXES not found")


def safe_fee(val):
    try:
        fee = float(val)
        return fee if fee > 0 else None
    except (TypeError, ValueError):
        return None


def load_labeled_fee_names():
    frames = []
    if LABELED_PATH.exists():
        df = pd.read_csv(LABELED_PATH, dtype={"udise_code": str})
        if "school_name" in df.columns and "fee" in df.columns:
            frames.append(df[["school_name", "fee"]].copy())

    if BANGALORE_PATH.exists():
        try:
            data = json.loads(BANGALORE_PATH.read_text(encoding="utf-8"))
            rows = []
            for item in data:
                fee = safe_fee(item.get("fee")) or safe_fee(item.get("fee_min"))
                if fee:
                    rows.append({"school_name": item.get("name"), "fee": fee})
            if rows:
                frames.append(pd.DataFrame(rows))
        except Exception:
            pass

    if not frames:
        return pd.DataFrame(columns=["school_name", "fee"])

    out = pd.concat(frames, ignore_index=True)
    out["school_name"] = out["school_name"].fillna("").astype(str)
    out["fee"] = pd.to_numeric(out["fee"], errors="coerce")
    out = out[out["fee"] > 0].copy()
    return out


def compute_fee_stats(regex_rows):
    stats = {
        r["key"]: {"fee_n": 0, "max_fee": None, "median_fee": None, "p90_fee": None}
        for r in regex_rows
    }
    fee_df = load_labeled_fee_names()
    if fee_df.empty:
        return stats

    matched = {r["key"]: [] for r in regex_rows}
    regex_rows_in_order = regex_rows
    for _, row in fee_df.iterrows():
        name = row["school_name"]
        fee = row["fee"]
        for rx in regex_rows_in_order:
            if rx["regex"].search(name):
                matched[rx["key"]].append(float(fee))
                break

    for key, fees in matched.items():
        if not fees:
            continue
        s = pd.Series(fees)
        stats[key] = {
            "fee_n": int(s.count()),
            "max_fee": float(s.max()),
            "median_fee": float(s.median()),
            "p90_fee": float(s.quantile(0.9)),
        }
    return stats


def load_examples(regex_rows):
    examples = {r["key"]: [] for r in regex_rows}
    counts = {r["key"]: 0 for r in regex_rows}
    if not PREDICTIONS_PATH.exists():
        return examples, counts

    df = pd.read_csv(PREDICTIONS_PATH, dtype={"udise_code": str})
    if "chain_detected" not in df.columns or "school_name" not in df.columns:
        return examples, counts

    df["confidence"] = pd.to_numeric(df.get("confidence"), errors="coerce")
    for key, grp in df.groupby("chain_detected", dropna=True):
        if key not in examples:
            continue
        counts[key] = len(grp)
        names = (
            grp.sort_values("confidence", ascending=False)["school_name"]
            .dropna()
            .astype(str)
            .drop_duplicates()
            .head(7)
            .tolist()
        )
        examples[key] = names
    return examples, counts


def shorten_pattern(pattern: str) -> str:
    pattern = pattern.replace("\\b", "")
    pattern = pattern.replace("\\s?", " ")
    pattern = pattern.replace("\\s", " ")
    pattern = pattern.replace("?:", "")
    pattern = pattern.replace("\\.?", ".")
    pattern = pattern.replace("\\'?", "'")
    pattern = re.sub(r"\s+", " ", pattern)
    return pattern.strip()


def format_inr(value):
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if value >= 100000:
        return f"Rs {value/100000:.1f}L"
    return f"Rs {value:,.0f}"


def fee_benchmark_text(stat):
    if not stat or not stat.get("fee_n"):
        return "No fee sample"
    return (
        f"Max {format_inr(stat['max_fee'])}<br/>"
        f"P90 {format_inr(stat['p90_fee'])}<br/>"
        f"Med {format_inr(stat['median_fee'])}<br/>"
        f"n={stat['fee_n']}"
    )


def on_page(canvas, doc):
    canvas.saveState()
    width, height = landscape(A4)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawRightString(width - 12 * mm, 8 * mm, f"Page {doc.page}")
    canvas.drawString(12 * mm, 8 * mm, "Premium school chain detection list - generated from classifier PREMIUM_REGEXES")
    canvas.restoreState()


def build_pdf():
    rows = extract_premium_regexes()
    examples, counts = load_examples(rows)
    fee_stats = compute_fee_stats(rows)
    rows = sorted(
        rows,
        key=lambda r: (
            fee_stats.get(r["key"], {}).get("fee_n", 0) > 0,
            fee_stats.get(r["key"], {}).get("p90_fee") or 0,
            fee_stats.get(r["key"], {}).get("max_fee") or 0,
            fee_stats.get(r["key"], {}).get("median_fee") or 0,
            counts.get(r["key"], 0),
        ),
        reverse=True,
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#101828"),
        spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "Subtitle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#475467"),
        spaceAfter=8,
    )
    small = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=5.7,
        leading=7,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#344054"),
    )
    small_gray = ParagraphStyle(
        "SmallGray",
        parent=small,
        textColor=colors.HexColor("#667085"),
    )
    header = ParagraphStyle(
        "Header",
        parent=small,
        fontName="Helvetica-Bold",
        fontSize=6.2,
        leading=7.2,
        alignment=TA_CENTER,
        textColor=colors.white,
    )
    name_style = ParagraphStyle(
        "Name",
        parent=small,
        fontName="Helvetica-Bold",
        fontSize=6.1,
        leading=7.2,
        textColor=colors.HexColor("#101828"),
    )

    doc = BaseDocTemplate(
        str(OUT_PDF),
        pagesize=landscape(A4),
        leftMargin=11 * mm,
        rightMargin=11 * mm,
        topMargin=10 * mm,
        bottomMargin=13 * mm,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])

    story = []
    story.append(Paragraph("Known Premium School Chain Detection List", title))
    detected_chain_count = sum(1 for k, c in counts.items() if c > 0)
    generated = dt.datetime.now().strftime("%d %b %Y, %I:%M %p")
    story.append(
        Paragraph(
            f"Client review draft generated from <b>PREMIUM_REGEXES</b>. "
            f"Contains <b>{len(rows)}</b> premium detection rules; "
            f"<b>{detected_chain_count}</b> chains currently have UDISE examples in the latest prediction file. "
            f"Sorted by observed fee premiumness from labeled fee data: P90 fee, then max fee, then median fee. "
            f"Generated: {generated}.",
            subtitle,
        )
    )
    story.append(
        Paragraph(
            "Use this to check whether the whitelist covers the major premium chains in each city. "
            "The tiny UDISE examples are actual names detected in the latest scored UDISE output where available; "
            "otherwise the detection expression is shown for review.",
            subtitle,
        )
    )

    data = [[
        Paragraph("#", header),
        Paragraph("Proper premium chain name", header),
        Paragraph("Fee benchmark", header),
        Paragraph("Detected ways / regex logic", header),
        Paragraph("Actual UDISE examples detected", header),
        Paragraph("UDISE count", header),
    ]]

    for i, row in enumerate(rows, 1):
        ex = examples.get(row["key"], [])
        ex_text = " | ".join(ex) if ex else "No current UDISE matches in latest output"
        data.append([
            Paragraph(str(i), small_gray),
            Paragraph(row["proper_name"], name_style),
            Paragraph(fee_benchmark_text(fee_stats.get(row["key"])), small_gray),
            Paragraph(shorten_pattern(row["pattern"]), small_gray),
            Paragraph(ex_text, small),
            Paragraph(str(counts.get(row["key"], 0)), small_gray),
        ])

    table = Table(
        data,
        colWidths=[8 * mm, 35 * mm, 25 * mm, 63 * mm, 115 * mm, 19 * mm],
        repeatRows=1,
        splitByRow=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1D2939")),
        ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#D0D5DD")),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#EAECF0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    doc.build(story)
    return OUT_PDF


if __name__ == "__main__":
    print(build_pdf())
