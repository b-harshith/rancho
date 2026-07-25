import os
import requests
import numpy as np

def get_valhalla_matrix(sources, targets, valhalla_url="http://localhost:8002", costing="auto"):
    """
    Query Valhalla sources_to_targets matrix endpoint.
    sources: list of (lat, lon) tuples
    targets: list of (lat, lon) tuples
    Returns: (distances_km, times_seconds) matrices of shape (len(sources), len(targets))
             or (None, None) if the request fails.
    """
    try:
        payload = {
            "sources": [{"lat": lat, "lon": lon} for lat, lon in sources],
            "targets": [{"lat": lat, "lon": lon} for lat, lon in targets],
            "costing": costing,
            "units": "kilometers"
        }
        response = requests.post(f"{valhalla_url}/sources_to_targets", json=payload, timeout=8.0)
        if response.status_code == 200:
            data = response.json()
            res = data.get("sources_to_targets")
            if not res:
                return None, None
            
            n_sources = len(sources)
            n_targets = len(targets)
            dist_matrix = np.zeros((n_sources, n_targets), dtype=np.float64)
            time_matrix = np.zeros((n_sources, n_targets), dtype=np.float64)
            
            if isinstance(res[0], list):
                for s_idx in range(n_sources):
                    for t_idx in range(n_targets):
                        item = res[s_idx][t_idx]
                        dist_matrix[s_idx, t_idx] = item.get("distance", 0.0)
                        time_matrix[s_idx, t_idx] = item.get("time", 0.0)
            else:
                for item in res:
                    s_idx = item.get("source_index", 0)
                    t_idx = item.get("target_index", 0)
                    if s_idx < n_sources and t_idx < n_targets:
                        dist_matrix[s_idx, t_idx] = item.get("distance", 0.0)
                        time_matrix[s_idx, t_idx] = item.get("time", 0.0)
            return dist_matrix, time_matrix
    except Exception:
        pass
    return None, None


def compute_routing_matrices(sources, targets, valhalla_url="http://localhost:8002", costing="auto", logger=None):
    """
    Computes routing matrices for sources and targets by batching requests.
    If Valhalla is offline or fails, returns (None, None).
    """
    n_sources = len(sources)
    n_targets = len(targets)
    
    # Fast connectivity test
    try:
        r = requests.get(f"{valhalla_url}/status", timeout=1.0)
    except Exception:
        # If status endpoint doesn't exist but server is listening, we'll try a dummy request
        try:
            requests.get(valhalla_url, timeout=0.8)
        except Exception:
            if logger:
                logger.log(f"Valhalla server unreachable at {valhalla_url}", "warning")
            return None, None
            
    if logger:
        logger.log(f"Querying Valhalla routing matrix ({n_sources} sources x {n_targets} targets)...")
        
    dist_matrix = np.zeros((n_sources, n_targets), dtype=np.float64)
    time_matrix = np.zeros((n_sources, n_targets), dtype=np.float64)
    
    # Valhalla has a maximum target size per request (often 100).
    # We will query target batch by target batch (e.g. 50 cells at a time) to prevent timeouts and respect limits.
    target_batch_size = 50
    source_batch_size = 50
    
    for s_start in range(0, n_sources, source_batch_size):
        s_end = min(s_start + source_batch_size, n_sources)
        s_batch = sources[s_start:s_end]
        
        for t_start in range(0, n_targets, target_batch_size):
            t_end = min(t_start + target_batch_size, n_targets)
            t_batch = targets[t_start:t_end]
            
            d_sub, t_sub = get_valhalla_matrix(s_batch, t_batch, valhalla_url, costing)
            if d_sub is None:
                if logger:
                    logger.log("Valhalla matrix request failed during batch query.", "warning")
                return None, None
                
            dist_matrix[s_start:s_end, t_start:t_end] = d_sub
            time_matrix[s_start:s_end, t_start:t_end] = t_sub
            
    return dist_matrix, time_matrix
