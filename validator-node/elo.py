
import math

K_FACTOR = 32

def expected_score(rating_a, rating_b):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def calculate_elo_changes(results_list, current_elos):
    """
    results_list: List of dicts with 'uname', 'position', 'total_time'
                  (Assumes sorted by position or finish order)
    current_elos: Dict {uname: elo_int}
    
    Returns: Dict {uname: elo_change_int}
    """
    changes = {res['uname']: 0 for res in results_list}
    
    # Pairwise comparison
    n = len(results_list)
    for i in range(n):
        for j in range(i + 1, n):
            # Player A (i) vs Player B (j)
            # Since sorted by position, i usually beats j
            # But check DNF status
            
            p_a = results_list[i]
            p_b = results_list[j]
            
            u_a = p_a['uname']
            u_b = p_b['uname']
            
            elo_a = current_elos.get(u_a, 1500)
            elo_b = current_elos.get(u_b, 1500)
            
            # Determine actual score
            # If both finished: A beats B (since i < j)
            # If A finished, B DNF: A beats B
            # If A DNF, B DNF: Draw (or ignore? LFS usually ranks DNFs by distance)
            # Assuming list is already sorted by rank (position)
            
            # Simple assumption: Higher rank (lower index) beats lower rank
            score_a = 1.0
            score_b = 0.0
            
            # Tie check (unlikely in racing unless exact same time)
            if p_a.get('total_time') == p_b.get('total_time') and p_a.get('total_time', 0) > 0:
                 score_a = 0.5
                 score_b = 0.5

            exp_a = expected_score(elo_a, elo_b)
            exp_b = expected_score(elo_b, elo_a)
            
            # Update changes
            # We divide K by (N-1) sometimes for multiplayer, OR use full pairwise
            # Full pairwise with fixed K can inflate/deflate rapidly in large fields.
            # A common variant for racing is K / (N-1) roughly, or just small K.
            # We will use standard pairwise but maybe scale K?
            # Let's stick to simple pairwise summation for now, maybe cap it.
            # Actually standard pairwise is fine for small grids (2-10).
            
            # Optimization: Use K / (N - 1) * 2 to keep scale similar to 1v1? 
            # No, let's just do pure pairwise.
            
            changes[u_a] += K_FACTOR * (score_a - exp_a)
            changes[u_b] += K_FACTOR * (score_b - exp_b)

    # Normalize/Round
    final_changes = {}
    for u, chg in changes.items():
        # In multiplayer, the sum of K updates can be large.
        # Often we normalize by number of opponents involved?
        # For LFS bot, let's normalize by (N-1) to keep it stable.
        if n > 1:
            final_changes[u] = int(round(chg / (n - 1)))
        else:
            final_changes[u] = 0
            
    return final_changes
