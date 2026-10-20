# Architecture & Technical Overview

This document provides a technical breakdown of the **TYG Archives** project, detailing the various modules and how they interact to provide a seamless, MIDI-controlled media installation.

## Core Modules (`core/`)

### 1. `player_engine.py` (Polyphonic Player Engine)
The `PlayerEngine` class manages simultaneous multi-clip playback using `python-vlc` offscreen instances combined with pure Qt widgets (`QLabel`) to prevent Cocoa z-order conflicts on macOS.
- **Polyphonic Slots:** Manages up to 3 concurrent voice slots (`VoiceSlot`).
- **Hold-to-play Model:** Clips only play while their MIDI note is held down. When `release_note()` is called on Note Off, the corresponding slot stops and is cleared from the canvas.
- **Out-point Pause:** When a video reaches its configured `out_point`, playback pauses on the last frame as long as the key is still held down.
- **Voice Stealing (FIFO):** If 3 voices are active and a 4th note is pressed, the oldest active voice is stopped and reassigned.
- **Dynamic Audio Attenuation:** Automatically divides audio volume according to active audio voices (100% for 1 voice, 50% for 2, 33% for 3) to prevent acoustic distortion.
- **Live Snapshot Rendering:** A unified Qt timer captures snapshots (~8 fps) from off-screen VLC decoders directly onto on-screen `QLabel` widgets.
- **Ghosting / Mosaic:** Potentiometer movements leave persistent ghost frames in a background pool (`FrozenFrame`).

### 2. `library.py` (Media Management)
Handles the discovery and synchronization of media files.
- **`scan_library()`:** Walks through a specified root directory, identifies year-based folders (e.g., `2012`), and registers valid media files (`.mp4`, `.mov`, `.jpg`, `.wav`, etc.).
- **`sync_library()`:** Merges newly discovered files with the existing `config.json` database, preserving manual edits (such as custom in/out points or manually assigned MIDI notes).
- **`auto_assign_midi()`:** Automatically assigns sequential MIDI notes (starting from note 28 / E0) to all media files within a specified year.

### 3. `midi_handler.py` (MIDI Listening Thread)
Provides a QThread-based listener for MIDI input to avoid blocking the main PyQt UI thread.
- **`MidiListener`:** Connects to a specified MIDI port using `mido`. Continuously listens for `note_on`, `note_off`, and `control_change` events.
- **Signals:** Emits PyQt signals (`note_on_signal`, `note_off_signal`, and `cc_signal`) intercepted by UI components.

### 4. `config.py` (Configuration Persistence)
A simple utility script that loads and saves application state (like mapped CC controls, chosen MIDI device, and the media library database) to a `config.json` file.

## User Interface Modules (`ui/`)

### 1. `main.py` (Launcher)
The entry point of the application. It creates a simple launcher window with buttons to access the three main modes: Preparation, Installation, and Settings.

### 2. `settings.py` (Settings Window)
Allows the user to configure hardware inputs.
- Scans and lists available MIDI devices.
- Provides a "Learn" feature. When activated, it spawns a temporary `MidiListener` thread that listens for the next CC message and binds it to a specific control (Scale, Pos X, or Pos Y) in `config.json`.

### 3. `prep_mode.py` (Preparation Mode)
An advanced 3-column workstation designed to curate and map media for the 76-key keyboard:
- **Column 1 (Media Pool & Years):** Discovers all available media for a selected year, displays usage count badges (`[x2]`, `[-]`), and supports drag-and-drop as well as filtering.
- **Column 2 (76-Key Keyboard Map):** Displays the complete range of 76 notes (Note 28 / E0 to Note 103 / G6). Supports drag-and-drop media assignment, note duplication for slicing sub-cues, clearing assignments, batch auto-assignment ("Fill All 76 Keys" and "1-to-1 Sequential"), and real-time MIDI keyboard auditioning.
- **Column 3 (VLC Player, Scrubber & Cue Trimmer):** Embedded VLC decoder with interactive timeline scrubber (`CueSlider` highlighting `[IN -> OUT]`), 0.1s spinboxes, keyboard shortcuts (`Space` for Play/Pause, `I` for Mark IN, `O` for Mark OUT), and dedicated "Audition Cue" playback.

### 4. `install_mode.py` (Installation Mode)
The primary runtime environment for the exhibition.
- **Full Screen Canvas:** Creates a borderless, black, full-screen canvas.
- **MIDI Integration:** Starts the `MidiListener` thread on the configured port.
- **Event Handling:** 
  - On `note_on`, matches the note in `config.json` and calls `PlayerEngine.trigger_note()`.
  - On `note_off`, calls `PlayerEngine.release_note()`.
  - On `control_change`, modifies the geometry of the most recently triggered active voice (`get_last_active_layer()`), generating ghost frames if moved significantly.

## Data Flow (Live Polyphonic Playback)
1. User selects a year from the combobox in **Install Mode**.
2. User presses and holds a key on the MIDI keyboard (`note_on`).
3. `InstallMode` matches the file in `config.json` and calls `PlayerEngine.trigger_note()`.
4. If less than 3 voices are active, an available slot plays the clip; if 3 are already active, the oldest voice is stopped (FIFO).
5. User presses additional keys while holding: up to 3 clips play simultaneously, with audio automatically attenuated.
6. When the user releases a key (`note_off`), `PlayerEngine.release_note()` stops that clip and removes it from the canvas.
7. If the user turns a knob, `InstallMode` updates the size/position of the most recent active clip.
