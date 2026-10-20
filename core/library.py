import os
import random
import subprocess
import json
from core.config import load_config, save_config

VALID_EXTENSIONS = {".mp4", ".mov", ".mkv", ".jpg", ".jpeg", ".png", ".wav"}

# Extensions vidéo pour lesquelles on génère des IN/OUT aléatoires
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def midi_note_to_name(note: int) -> str:
    """Convertit un numéro de note MIDI en nom musical (ex: 28 -> 'E0', 60 -> 'C3', 103 -> 'G6')."""
    if note is None or note < 0 or note > 127:
        return ""
    name = NOTE_NAMES[note % 12]
    octave = (note // 12) - 2
    return f"{name}{octave}"

_video_info_cache = {}

def _get_video_info(filepath):
    """Récupère la durée et les dimensions d'une vidéo via ffprobe (avec cache et chemins de secours)."""
    if filepath in _video_info_cache:
        return _video_info_cache[filepath]
        
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
                        
                info = {"duration": duration, "width": width, "height": height}
                _video_info_cache[filepath] = info
                return info
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
            continue
            
    info = {"duration": 0.0, "width": 0, "height": 0}
    return info

def get_media_pool(year, config=None):
    """Retourne la liste des médias uniques disponibles pour l'année donnée."""
    if config is None:
        config = load_config()
    
    # 1. Priorité au media_pool dédié s'il existe
    pool = config.get("media_pool", {}).get(str(year))
    if pool:
        for m in pool:
            if m.get("type") == "video" and (m.get("duration", 0) <= 0 or m.get("width", 0) <= 0):
                info = _get_video_info(m["filepath"])
                m["duration"] = info["duration"]
                m["width"] = info["width"]
                m["height"] = info["height"]
        return pool
        
    # 2. Rétro-compatibilité : déduire le pool depuis la liste d'assignation years[year]
    existing = config.get("years", {}).get(str(year), [])
    seen = set()
    deduced_pool = []
    for item in existing:
        fp = item.get("filepath", "")
        if fp and fp not in seen:
            seen.add(fp)
            mtype = item.get("type", "video")
            w = item.get("width", 0)
            h = item.get("height", 0)
            dur = item.get("duration", 0.0)
            
            if mtype == "video" and (dur <= 0 or w <= 0 or h <= 0):
                info = _get_video_info(fp)
                dur = info["duration"]
                w = info["width"]
                h = info["height"]
                
            deduced_pool.append({
                "filepath": fp,
                "type": mtype,
                "width": w,
                "height": h,
                "duration": dur
            })
    return deduced_pool

def generate_slice_points(filepath, duration=None, width=None, height=None):
    """Génère des points IN et OUT aléatoires pour un clip vidéo en évitant les noirs de début de bande."""
    if duration is None or duration <= 0 or not width or not height:
        info = _get_video_info(filepath)
        dur = info["duration"]
        w = info["width"]
        h = info["height"]
    else:
        dur = duration
        w = width
        h = height
    
    if dur > 10:
        # Éviter le noir de début de bande (présent sur les numérisations VHS/Hi8/U-matic)
        # On commence au minimum à 8 secondes (ou 5% du clip) pour garantir l'image
        min_start = min(8.0, dur * 0.05) if dur > 20 else 0.0
        max_in = dur * 0.75
        in_p = round(random.uniform(min_start, max_in), 1)
        
        # OUT point : au moins 8s de vidéo, jusqu'à 120s ou la fin du clip
        min_out = min(in_p + 8.0, dur)
        max_out = min(in_p + 120.0, dur)
        out_p = round(random.uniform(min_out, max_out), 1)
        return in_p, out_p, w, h, dur
    elif dur > 0:
        return 0.0, round(dur, 1), w, h, dur
    else:
        return 0.0, 0.0, w, h, 0.0

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
                        
                        info = _get_video_info(filepath) if mtype == "video" else {"duration": 0.0, "width": 0, "height": 0}
                        
                        years_data[year_dir].append({
                            "filepath": filepath,
                            "type": mtype,
                            "width": info["width"],
                            "height": info["height"],
                            "duration": info["duration"]
                        })
                        
            # Trier les fichiers par nom alphabétique dans chaque année
            years_data[year_dir].sort(key=lambda f: os.path.basename(f["filepath"]).lower())
            
    return years_data

def sync_library(root_path):
    config = load_config()
    scanned_pools = scan_library(root_path)
    
    # Stocker les fichiers scannés dans le media_pool
    media_pool = config.setdefault("media_pool", {})
    for year, files in scanned_pools.items():
        media_pool[year] = files
        
    # Conserver les assignations existantes dans years[year]
    existing_years = config.setdefault("years", {})
    for year, pool_files in scanned_pools.items():
        if year not in existing_years:
            # Année nouvellement scannée : créer une assignation séquentielle par défaut
            existing_years[year] = []
            note = 28
            for f in pool_files:
                in_p, out_p, w, h, dur = generate_slice_points(f["filepath"], f.get("duration"), f.get("width"), f.get("height"))
                existing_years[year].append({
                    "midi_note": note,
                    "filepath": f["filepath"],
                    "type": f["type"],
                    "in_point": in_p if f["type"] == "video" else 0.0,
                    "out_point": out_p if f["type"] == "video" else 0.0,
                    "width": w,
                    "height": h
                })
                note += 1
                if note > 103:
                    break
        else:
            # Filtrer pour ne garder que les assignations de fichiers qui existent toujours
            scanned_paths = {f["filepath"] for f in pool_files}
            cleaned_assignments = [
                a for a in existing_years[year] 
                if a.get("filepath") in scanned_paths
            ]
            existing_years[year] = cleaned_assignments
            
    save_config(config)
    return existing_years

def auto_assign_fill(year, min_note=28, max_note=103):
    """Assigne en boucle les médias du pool pour remplir toutes les touches de min_note à max_note avec des cues uniques."""
    config = load_config()
    pool = get_media_pool(year, config)
    if not pool:
        print(f"[Library] Media pool vide pour l'année {year}")
        return
        
    assignments = []
    pool_len = len(pool)
    
    for idx, note in enumerate(range(min_note, max_note + 1)):
        media = pool[idx % pool_len]
        fp = media["filepath"]
        mtype = media.get("type", "video")
        
        if mtype == "video":
            in_p, out_p, w, h, dur = generate_slice_points(fp, media.get("duration"), media.get("width"), media.get("height"))
        else:
            in_p, out_p, w, h = 0.0, 0.0, media.get("width", 0), media.get("height", 0)
            
        assignments.append({
            "midi_note": note,
            "filepath": fp,
            "type": mtype,
            "in_point": in_p,
            "out_point": out_p,
            "width": w,
            "height": h
        })
        
    config.setdefault("years", {})[str(year)] = assignments
    save_config(config)
    print(f"[Library] Auto-assign 'Fill' terminé pour {year} ({len(assignments)} notes assignées de {min_note} à {max_note})")

def auto_assign_sequential(year, min_note=28, max_note=103):
    """Assigne chaque média du pool une seule fois de manière séquentielle."""
    config = load_config()
    pool = get_media_pool(year, config)
    if not pool:
        print(f"[Library] Media pool vide pour l'année {year}")
        return
        
    assignments = []
    for idx, media in enumerate(pool):
        note = min_note + idx
        if note > max_note:
            break
            
        fp = media["filepath"]
        mtype = media.get("type", "video")
        
        if mtype == "video":
            in_p, out_p, w, h, dur = generate_slice_points(fp, media.get("duration"), media.get("width"), media.get("height"))
        else:
            in_p, out_p, w, h = 0.0, 0.0, media.get("width", 0), media.get("height", 0)
            
        assignments.append({
            "midi_note": note,
            "filepath": fp,
            "type": mtype,
            "in_point": in_p,
            "out_point": out_p,
            "width": w,
            "height": h
        })
        
    config.setdefault("years", {})[str(year)] = assignments
    save_config(config)
    print(f"[Library] Auto-assign 'Sequential' terminé pour {year} ({len(assignments)} notes assignées)")

def heal_zero_cues(year=None):
    """Répare les assignations vidéo qui ont IN=0 et OUT=0 ou des dimensions nulles."""
    config = load_config()
    years_to_check = [str(year)] if year else list(config.get("years", {}).keys())
    repaired_count = 0
    
    for y in years_to_check:
        items = config.get("years", {}).get(y, [])
        for item in items:
            if item.get("type") == "video":
                fp = item.get("filepath", "")
                in_p = item.get("in_point", 0.0)
                out_p = item.get("out_point", 0.0)
                w = item.get("width", 0)
                h = item.get("height", 0)
                
                # Si in=0 et out=0, ou dimensions inconnues
                if (in_p == 0.0 and out_p == 0.0) or w <= 0 or h <= 0:
                    new_in, new_out, new_w, new_h, dur = generate_slice_points(fp)
                    if in_p == 0.0 and out_p == 0.0:
                        item["in_point"] = new_in
                        item["out_point"] = new_out
                    if w <= 0 or h <= 0:
                        item["width"] = new_w
                        item["height"] = new_h
                    repaired_count += 1
                    
    if repaired_count > 0:
        save_config(config)
        print(f"[Library] {repaired_count} assignations vidéo réparées avec des cues et dimensions valides.")
    return repaired_count

def auto_assign_midi(year, mode="fill"):
    """Alias rétro-compatible pour auto-assignation."""
    if mode == "sequential":
        auto_assign_sequential(year)
    else:
        auto_assign_fill(year)
