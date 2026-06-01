
# Car Class Definitions (Strict Performance Groups)
# Only merging cars that are officially BOP'd or identical in pace.

CAR_CLASSES = {
    # --- Balanced Classes (BOP) ---
    'GTI': ['XFG', 'XRG'],           # Classic GTI Class
    'TBO': ['XRT', 'RB4', 'FXO'],    # Classic Turbo Class
    'GTR': ['FXR', 'XRR', 'FZR'],    # Main GTR Class
    
    # --- Single Car Classes (Significant differences) ---
    'UF1': ['UF1'],
    'LX4': ['LX4'],
    'LX6': ['LX6'], # Faster than LX4
    'RAC': ['RAC'],
    'FZ5': ['FZ5'], # Differnet from RAC
    'UFR': ['UFR'],
    'XFR': ['XFR'], # Often faster/different than UFR
    'MRT': ['MRT'],
    'FBM': ['FBM'],
    'FOX': ['FOX'],
    'FO8': ['FO8'],
    'BF1': ['BF1'],
    
    # --- Mods ---
    'MOD': []
}

# Reverse Map for fast lookup
CAR_TO_CLASS = {}
for cat, cars in CAR_CLASSES.items():
    for car in cars:
        if car not in CAR_TO_CLASS:
            CAR_TO_CLASS[car] = cat

def get_car_category(car_name: str) -> str:
    """
    Returns the category code for a given car name.
    If unknown (mod), returns 'MOD'.
    """
    c = car_name.strip().upper()
    
    # Direct match
    if c in CAR_TO_CLASS:
        return CAR_TO_CLASS[c]
        
    return 'MOD'
