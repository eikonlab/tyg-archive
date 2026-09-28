import json
import os

CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {
            "audio_device": "",
            "midi_input": "",
            "cc_scale": None,
            "cc_pos_x": None,
            "cc_pos_y": None,
            "years": {}
        }
    with open(CONFIG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"audio_device": "", "midi_input": "", "years": {}}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)
