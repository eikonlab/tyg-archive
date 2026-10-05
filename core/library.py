import os
import random
import subprocess
import json
from core.config import load_config, save_config

VALID_EXTENSIONS = {".mp4", ".mov", ".mkv", ".jpg", ".jpeg", ".png", ".wav"}

# Extensions vidéo pour lesquelles on génère des IN/OUT aléatoires
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


def _get_video_info(filepath):
    """Récupère la durée et les dimensions d'une vidéo via ffprobe (avec chemins de secours)."""
    ffprobe_paths = ["ffprobe", "/usr/local/bin/ffprobe", "/opt/homebrew/bin/ffprobe", "/opt/ffmpeg/bin/ffprobe"]
    
    for cmd in ffprobe_paths:
        try:
            result = subprocess.run(
                [cmd, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", filepath],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration = float(data.get("format", {}).get("duration", 0))
                
                width, height = 0, 0
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        width = int(stream.get("width", 0))
                        height = int(stream.get("height", 0))
                        break
                        
                return {"duration": duration, "width": width, "height": height}
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
            continue
            
    return {"duration": 0.0, "width": 0, "height": 0}


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
                        
            # Trier les fichiers par nom alphabétique dans chaque année
            years_data[year_dir].sort(key=lambda f: os.path.basename(f["filepath"]).lower())
            
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
    """Auto-assigne les notes MIDI et randomise les IN/OUT pour les vidéos."""
    config = load_config()
    if year not in config["years"]:
        return
        
    print(f"[Library] Auto-assign MIDI pour {year} ({len(config['years'][year])} fichiers)")
    
    note = 36  # Start at C1
    for f in config["years"][year]:
        f["midi_note"] = note
        note += 1
        if note > 127:
            break
        
        # Randomiser les IN/OUT pour les vidéos
        ext = os.path.splitext(f["filepath"])[1].lower()
        
        # Par défaut, on initialise avec des dimensions nulles
        f["width"] = 0
        f["height"] = 0
        
        if ext in VIDEO_EXTENSIONS:
            info = _get_video_info(f["filepath"])
            duration = info["duration"]
            f["width"] = info["width"]
            f["height"] = info["height"]
            
            if duration > 10:
                # IN point : position aléatoire dans les premiers 80% du clip
                # pour laisser au moins 20% de clip à jouer
                max_in = duration * 0.8
                in_point = round(random.uniform(0, max_in), 1)
                
                # OUT point : entre le in_point + 5s et la fin du clip
                min_out = min(in_point + 5.0, duration)
                out_point = round(random.uniform(min_out, duration), 1)
                
                f["in_point"] = in_point
                f["out_point"] = out_point
                print(f"  {os.path.basename(f['filepath'])}: IN={in_point}s OUT={out_point}s (durée={duration:.0f}s) ({f['width']}x{f['height']})")
            elif duration > 0:
                # Clip court : on garde le début mais avec un out aléatoire
                f["in_point"] = 0.0
                f["out_point"] = round(random.uniform(duration * 0.3, duration), 1)
                print(f"  {os.path.basename(f['filepath'])}: clip court, IN=0 OUT={f['out_point']}s ({f['width']}x{f['height']})")
            else:
                print(f"  {os.path.basename(f['filepath'])}: durée inconnue (ffprobe indisponible?)")
    
    save_config(config)
