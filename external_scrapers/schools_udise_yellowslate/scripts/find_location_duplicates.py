import json
import math

def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000.0 # meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def main():
    path = "/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/static/data/schools_delhi_ncr.json"
    with open(path, "r", encoding="utf-8") as f:
        schools = json.load(f)
        
    print(f"Loaded {len(schools)} schools.")
    
    # Find close proximity pairs
    close_pairs = []
    seen_pairs = set()
    
    for i in range(len(schools)):
        for j in range(i + 1, len(schools)):
            s1 = schools[i]
            s2 = schools[j]
            dist = haversine_m(s1["lat"], s1["lon"], s2["lat"], s2["lon"])
            if dist <= 50: # 50 meters
                pair_key = tuple(sorted([s1["name"], s2["name"]]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    close_pairs.append((dist, s1, s2))
                    
    print(f"Found {len(close_pairs)} close proximity pairs (<= 50m):")
    for dist, s1, s2 in sorted(close_pairs, key=lambda x: x[0]):
        print(f"\nDistance: {dist:.1f}m")
        print(f"  School 1: {s1['name']} (Fee: {s1['fee']}, Students: {s1['students']}, Board: {s1['board']})")
        print(f"  School 2: {s2['name']} (Fee: {s2['fee']}, Students: {s2['students']}, Board: {s2['board']})")

if __name__ == "__main__":
    main()
