def calculate_elo(results: list):
    """
    Updates the 'new_elo' and 'elo_change' fields in the results list in-place.
    Each item in results must have: 'position', 'elo'.
    """
    n = len(results)
    if n < 1: return
    
    K_FACTOR = 32
    
    for p_i in results:
        # Actual Score for p_i:
        # formula: (N - p_i_pos) / (N - 1)
        # 1st place (pos 1): (N-1)/(N-1) = 1.0
        # Last place (pos N): 0/(N-1) = 0.0
        
        # Note: position should be 1-based usually
        if 'position' not in p_i: continue
        
        try:
            actual = (n - p_i['position']) / (n - 1)
        except ZeroDivisionError:
            actual = 1.0 # Only 1 player? Should be caught by n<2 but safe guard.
            
        # Expected Score
        expected_sum = 0
        count = 0
        
        current_elo = p_i.get('elo', 1500)
        
        for p_j in results:
            if p_j == p_i: continue
            
            opponent_elo = p_j.get('elo', 1500)
            
            # E_A = 1 / (1 + 10 ^ ((Rb - Ra)/400))
            expected = 1 / (1 + 10 ** ((opponent_elo - current_elo) / 400))
            expected_sum += expected
            count += 1
            
        if count == 0:
            # Solo Race?
            # If solo, maybe gain small +1 for finishing?
            # Or just skip.
            # But user wants to see *something*
            p_i['new_elo'] = current_elo
            p_i['elo_change'] = 0
            continue
        
        # Average expected score against all opponents? 
        # The logic in system2 was:
        # expected = sum(...) / (n - 1)
        
        avg_expected = expected_sum / (n - 1)
        
        change = K_FACTOR * (actual - avg_expected)
        
        p_i['new_elo'] = round(current_elo + change)
        p_i['elo_change'] = p_i['new_elo'] - current_elo
