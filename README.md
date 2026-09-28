# TYG Archives

TYG Archives is an interactive, MIDI-controlled media playback installation. Built with Python, PyQt5, and VLC, it allows users to trigger and manipulate video, image, and audio files from categorized archival years using a MIDI keyboard or controller.

## Features

- **Media Playback Engine:** Uses `python-vlc` to overlay up to 3 media layers simultaneously. When a new media is triggered, it dynamically replaces the oldest layer (Round-Robin) and appears at a randomized size and position.
- **MIDI Integration:** Built with `mido` and `python-rtmidi`. Map MIDI notes to trigger specific files, and use Control Change (CC) messages (potentiometers/knobs) to manipulate the scale, X-position, and Y-position of the active media in real-time.
- **Library Management:** Scans structured directories (organized by Year) and generates a JSON-based library (`config.json`), automatically assigning MIDI notes to media files.
- **Multi-Mode Interface:**
  - **Preparation Mode:** For scanning directories and assigning MIDI notes.
  - **Installation Mode:** A full-screen, live performance/exhibition view where MIDI inputs trigger the media.
  - **Settings:** For selecting the MIDI input device and using a "Learn" feature to map MIDI CC knobs.

## Requirements

- Python 3.x
- VLC Media Player installed on your system.
- Requirements installed via `pip`:
  ```bash
  pip install PyQt5 python-vlc mido python-rtmidi
  ```

## Project Structure

Your media files should be organized by year in a root directory. For example:
```text
MyMediaLibrary/
├── 2010/
│   ├── video1.mp4
│   └── image1.jpg
├── 2012/
│   └── video2.mov
└── 2015/
    └── audio1.wav
```

## How to Run

1. **Activate your virtual environment (if applicable):**
   ```bash
   source venv/bin/activate
   ```
2. **Run the Application:**
   ```bash
   python main.py
   ```

## Usage Workflow

1. **Settings (MIDI Setup)**
   - Open **Paramètres (MIDI / Audio)**.
   - Select your MIDI input device from the dropdown.
   - Click **Learn Scale**, **Learn Pos X**, or **Learn Pos Y** and turn a knob on your MIDI controller to map it. Save and close.
2. **Preparation Mode (Library Building)**
   - Open **Mode Préparation**.
   - Click **Scanner un dossier...** and select your root media directory (e.g., `MyMediaLibrary/`).
   - Select a year from the list and click **Auto-Assigner MIDI** to automatically assign MIDI notes to those files (starting from Note 36 / C1).
3. **Installation Mode (Live Playback)**
   - Open **Mode Installation**. The app will go full-screen.
   - Select a year from the dropdown at the top.
   - Press the assigned keys on your MIDI keyboard to trigger media files. They will appear on screen.
   - Turn your assigned MIDI knobs to adjust the size and position of the most recently triggered video.
   - Press `Escape` to exit.
