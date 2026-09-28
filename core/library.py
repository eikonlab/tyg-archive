import os
from core.config import load_config, save_config

VALID_EXTENSIONS = {".mp4", ".mov", ".mkv", ".jpg", ".jpeg", ".png", ".wav"}

def scan_library(root_path):
    years_data = {}
    if not os.path.isdir(root_path):
        return years_data
        
    for year_dir in os.listdir(root_path):
        year_path = os.path.join(root_path, year_dir)
        if os.path.isdir(year_path) and year_dir.isdigit():
            years_data[year_dir] = []
            
            for root, _, files in os.walk(year_path):
                for f in files:
                    if f.startswith('.'):
                        continue
                    
                    ext = os.path.splitext(f)[1].lower()
                    if ext in VALID_EXTENSIONS:
                        filepath = os.path.join(root, f)
                        mtype = "image" if ext in {".jpg", ".jpeg", ".png"} else ("audio" if ext == ".wav" else "video")
                        
                        years_data[year_dir].append({
                            "filepath": filepath,
                            "type": mtype,
                            "in_point": 0.0,
                            "out_point": 0.0,
                            "midi_note": None
                        })
    return years_data

def sync_library(root_path):
    config = load_config()
    scanned = scan_library(root_path)
    
    # Merge preserving existing midi notes and cue points
    existing_years = config.get("years", {})
    
    for year, files in scanned.items():
        if year not in existing_years:
            existing_years[year] = files
        else:
            # Map existing files by path for quick lookup
            existing_files = {f["filepath"]: f for f in existing_years[year]}
            merged = []
            for f in files:
                if f["filepath"] in existing_files:
                    merged.append(existing_files[f["filepath"]])
                else:
                    merged.append(f)
            existing_years[year] = merged
            
    config["years"] = existing_years
    save_config(config)
    return existing_years

def auto_assign_midi(year):
    config = load_config()
    if year in config["years"]:
        note = 36 # Start at C1
        for f in config["years"][year]:
            f["midi_note"] = note
            note += 1
            if note > 127:
                break
        save_config(config)
