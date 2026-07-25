#!/usr/bin/env python3
import json
import argparse
import sys
import time
from pathlib import Path

# Try to import h3
try:
    import h3
except ImportError:
    print("Error: The 'h3' library is not installed in the python environment.", file=sys.stderr)
    print("Please run: pip install h3", file=sys.stderr)
    sys.exit(1)

def parse_args():
    parser = argparse.ArgumentParser(
        description="Suggest top 8 micro-markets, where each consists of exactly 8 contiguous hexes."
    )
    parser.add_argument(
        "--weight-units",
        type=float,
        default=0.5,
        help="Weight for normalized total housing units (0.0 to 1.0). Default is 0.5."
    )
    parser.add_argument(
        "--weight-score",
        type=float,
        default=0.5,
        help="Weight for normalized average affluence score (0.0 to 1.0). Default is 0.5."
    )
    parser.add_argument(
        "--min-avg-score",
        type=float,
        default=0.0,
        help="Minimum average affluence score for any individual hex in the market. Default is 0.0."
    )
    parser.add_argument(
        "--max-radius",
        type=int,
        default=2,
        help="Maximum H3 ring distance from seed hex to restrict candidate nodes (ensures compactness). "
             "Default is 2 (2-ring). Use 0 for unrestricted (allows any contiguous shape of size 8)."
    )
    parser.add_argument(
        "--geojson-path",
        type=str,
        default=None,
        help="Path to the hexes.geojson file. Default auto-resolves relative to script location."
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to save the output suggestion results (JSON format)."
    )
    return parser.parse_args()

def load_hex_data(geojson_path):
    if not geojson_path:
        # Default path relative to this script: src/public/data/hexes.geojson
        script_dir = Path(__file__).resolve().parent
        geojson_path = script_dir / "public" / "data" / "hexes.geojson"
    else:
        geojson_path = Path(geojson_path)

    if not geojson_path.exists():
        print(f"Error: GeoJSON file not found at {geojson_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading hex data from: {geojson_path.name}...")
    with open(geojson_path, "r") as f:
        data = json.load(f)

    features = data.get("features", [])
    hexes = {}
    
    for feat in features:
        props = feat.get("properties", {})
        hex_id = props.get("hex_id")
        if not hex_id:
            continue
        
        # Extract metrics
        name = props.get("name", hex_id)
        units = float(props.get("direct_total_units") or 0.0)
        score = float(props.get("final_affluence_score") or 0.0)
        family_tam = float(props.get("countable_family_tam") or 0.0)
        refined_segment = props.get("refined_budget_segment", "Unknown")
        top_societies = props.get("top_societies", "")
        
        hexes[hex_id] = {
            "hex_id": hex_id,
            "name": name,
            "units": units,
            "score": score,
            "family_tam": family_tam,
            "refined_segment": refined_segment,
            "top_societies": top_societies,
            "geometry": feat.get("geometry")
        }
    
    print(f"Successfully loaded {len(hexes)} active hexes.")
    return hexes

def build_adjacency_graph(hexes):
    active_ids = set(hexes.keys())
    adj = {hid: set() for hid in active_ids}
    for hid in active_ids:
        try:
            neighbors = h3.grid_ring(hid, 1)
        except Exception:
            try:
                neighbors = h3.k_ring(hid, 1)
            except Exception:
                neighbors = []
        for nb in neighbors:
            if nb in active_ids:
                adj[hid].add(nb)
                adj[nb].add(hid)
    return adj

def get_k_ring(seed, k):
    try:
        return h3.grid_disk(seed, k)
    except Exception:
        try:
            return h3.k_ring(seed, k)
        except Exception:
            return {seed}

def generate_size_8_subgraphs(hexes, adj, max_radius):
    nodes_list = sorted(list(hexes.keys()))
    node_to_idx = {node: i for i, node in enumerate(nodes_list)}
    
    unique_subgraphs = []
    seen_sets = set()
    
    t0 = time.time()
    
    # Restrict to k-ring if max_radius > 0
    def grow(seed_idx, S, candidates, allowed_indices):
        if len(S) == 8:
            fs = frozenset(S)
            if fs not in seen_sets:
                seen_sets.add(fs)
                unique_subgraphs.append(fs)
            return
            
        cand_list = list(candidates)
        for i, v in enumerate(cand_list):
            new_S = S | {v}
            new_cand = set(cand_list[i+1:])
            for nb in adj[nodes_list[v]]:
                nb_idx = node_to_idx[nb]
                if nb_idx > seed_idx and nb_idx not in new_S:
                    if allowed_indices is None or nb_idx in allowed_indices:
                        new_cand.add(nb_idx)
            grow(seed_idx, new_S, new_cand, allowed_indices)

    print(f"Generating size-8 contiguous subgraphs (Compactness max_radius={max_radius})...")
    
    for seed_idx, seed in enumerate(nodes_list):
        allowed_indices = None
        if max_radius > 0:
            k_ring = get_k_ring(seed, max_radius)
            allowed_indices = {node_to_idx[nb] for nb in k_ring if nb in node_to_idx}
            
        initial_candidates = set()
        for nb in adj[seed]:
            nb_idx = node_to_idx[nb]
            if nb_idx > seed_idx:
                if allowed_indices is None or nb_idx in allowed_indices:
                    initial_candidates.add(nb_idx)
                    
        grow(seed_idx, {seed_idx}, initial_candidates, allowed_indices)
        
    t1 = time.time()
    print(f"Generated {len(unique_subgraphs)} unique size-8 contiguous subgraphs in {t1 - t0:.2f} seconds.")
    
    # Map node indices back to actual hex IDs
    mapped_subgraphs = []
    for s in unique_subgraphs:
        mapped_subgraphs.append([nodes_list[idx] for idx in s])
        
    return mapped_subgraphs

def main():
    args = parse_args()
    
    # Load data and build graph
    hexes = load_hex_data(args.geojson_path)
    if not hexes:
        print("No active hexes. Exiting.", file=sys.stderr)
        return
        
    adj = build_adjacency_graph(hexes)
    
    # Generate size-8 subgraphs
    subgraphs = generate_size_8_subgraphs(hexes, adj, args.max_radius)
    if not subgraphs:
        print("No contiguous size-8 subgraphs found. Exiting.")
        return
        
    # Calculate metrics for each subgraph
    candidate_markets = []
    for s_nodes in subgraphs:
        # Check min avg score filter or other individual node filters if needed
        # We also enforce that no hex in the subgraph has a score below min_avg_score
        if args.min_avg_score > 0:
            if any(hexes[h]["score"] < args.min_avg_score for h in s_nodes):
                continue
                
        total_units = sum(hexes[h]["units"] for h in s_nodes)
        avg_score = sum(hexes[h]["score"] for h in s_nodes) / 8.0
        total_tam = sum(hexes[h]["family_tam"] for h in s_nodes)
        
        candidate_markets.append({
            "hex_ids": s_nodes,
            "total_units": total_units,
            "avg_score": avg_score,
            "total_tam": total_tam
        })
        
    if not candidate_markets:
        print("No subgraphs passed the filters. Exiting.")
        return
        
    # Normalize metrics
    max_units = max(m["total_units"] for m in candidate_markets)
    min_units = min(m["total_units"] for m in candidate_markets)
    
    max_score = max(m["avg_score"] for m in candidate_markets)
    min_score = min(m["avg_score"] for m in candidate_markets)
    
    range_units = max(1.0, max_units - min_units)
    range_score = max(1.0, max_score - min_score)
    
    for m in candidate_markets:
        norm_units = 100.0 * (m["total_units"] - min_units) / range_units
        norm_score = 100.0 * (m["avg_score"] - min_score) / range_score
        
        m["norm_units"] = round(norm_units, 2)
        m["norm_score"] = round(norm_score, 2)
        
        # Combined score
        m["combined_score"] = round(
            (args.weight_units * norm_units) + (args.weight_score * norm_score), 2
        )
        
    # Sort candidate markets by combined score descending
    candidate_markets.sort(key=lambda x: x["combined_score"], reverse=True)
    
    # 1. Top 8 Overlapping Candidates
    top_8_overlapping = candidate_markets[:8]
    
    # 2. Greedy Disjoint Selection
    disjoint_markets = []
    used_hexes = set()
    for m in candidate_markets:
        # Check if this candidate shares any hex with already selected ones
        if not used_hexes.intersection(m["hex_ids"]):
            disjoint_markets.append(m)
            used_hexes.update(m["hex_ids"])
            if len(disjoint_markets) == 8:
                break
                
    # Helper to print market table
    def print_market_table(markets, title):
        print("\n" + "=" * 115)
        print(f" {title.upper()}")
        print(f" Weights: Housing Units = {args.weight_units:.2f}, Affluence Score = {args.weight_score:.2f}")
        print("=" * 115)
        print(f"{'Rank':<5} | {'Core Hex / Primary Area':<35} | {'Total Units':<11} | {'Avg Score':<9} | {'Total TAM':<9} | {'Comb. Score':<11}")
        print("-" * 115)
        
        for idx, m in enumerate(markets, 1):
            # Pick the highest scoring hex in the market as the representative core name
            core_hex = max(m["hex_ids"], key=lambda h: hexes[h]["score"])
            core_name = hexes[core_hex]["name"]
            
            # Create a string of other area names in the market (truncated)
            other_names = [hexes[h]["name"] for h in m["hex_ids"] if h != core_hex]
            desc_str = f"{core_name} (+ {', '.join(other_names)})"
            if len(desc_str) > 35:
                desc_str = desc_str[:32] + "..."
                
            print(f"#{idx:<4} | {desc_str:<35} | {m['total_units']:<11.0f} | {m['avg_score']:<9.2f} | {m['total_tam']:<9.0f} | {m['combined_score']:<11.2f}")
        print("=" * 115)
        
    print_market_table(top_8_overlapping, "Top 8 Individual Candidate Micro-Markets (Overlapping Allowed)")
    print_market_table(disjoint_markets, "8 Recommended Disjoint Micro-Markets (No Overlapping Hexes)")
    
    # Print detailed description of recommended disjoint micro-markets
    print("\n" + "=" * 115)
    print(" DETAILED RECOMMENDED DISJOINT MICRO-MARKET ANALYSES")
    print("=" * 115)
    for idx, m in enumerate(disjoint_markets, 1):
        core_hex = max(m["hex_ids"], key=lambda h: hexes[h]["score"])
        print(f"\nMICRO-MARKET #{idx}: Core Area = {hexes[core_hex]['name']}")
        print(f"  • Combined Score : {m['combined_score']} (Total Units: {m['total_units']:.0f}, Avg Score: {m['avg_score']:.2f}, Total TAM: {m['total_tam']:.0f})")
        print(f"  • Consists of the following 8 contiguous hexes:")
        for h in sorted(m["hex_ids"], key=lambda x: hexes[x]["score"], reverse=True):
            h_info = hexes[h]
            print(f"    - {h_info['name']:<30} [{h}] | Score: {h_info['score']:.1f} | Units: {h_info['units']:.0f} | TAM: {h_info['family_tam']:.0f}")
            if h_info['top_societies']:
                # Shorten society list
                soc_list = h_info['top_societies'].split(" | ")[:2]
                print(f"      Key Societies: {' | '.join(soc_list)}")
        print("-" * 75)
        
    # Write to output file if requested
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        output_data = {
            "metadata": {
                "weight_units": args.weight_units,
                "weight_score": args.weight_score,
                "min_avg_score": args.min_avg_score,
                "max_radius": args.max_radius,
                "max_units_in_dataset": max_units,
                "min_units_in_dataset": min_units,
                "max_score_in_dataset": max_score,
                "min_score_in_dataset": min_score
            },
            "top_overlapping_candidates": top_8_overlapping,
            "disjoint_micro_markets": disjoint_markets
        }
        with open(out_path, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nSaved detailed suggestions to: {out_path}")

if __name__ == "__main__":
    main()
