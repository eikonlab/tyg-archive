# Architecture & Technical Overview

This document provides a technical breakdown of the **TYG Archives** project, detailing the various modules and how they interact to provide a seamless, MIDI-controlled media installation.

## Core Modules (`core/`)

### 1. `player_engine.py` (VLC Integration)
The `PlayerEngine` class manages the playback of media files using the `python-vlc` bindings.
- **Layers:** It initializes with a fixed number of layers (default 3), represented by the `PlayerLayer` class.
- **Round-Robin Playback:** When a new media file is triggered via `play_media`, it stops the oldest active layer, calculates a random size (30-70% of the screen) and position, assigns the new media to that layer, and raises its widget to the top of the stack.
- **Dynamic Control:** Provides `get_last_active_layer()` so that CC messages from the MIDI controller can manipulate the currently active layer in real-time.

### 2. `library.py` (Media Management)
Handles the discovery and synchronization of media files.
- **`scan_library()`:** Walks through a specified root directory, identifies year-based folders (e.g., `2012`), and registers valid media files (`.mp4`, `.mov`, `.jpg`, `.wav`, etc.).
- **`sync_library()`:** Merges newly discovered files with the existing `config.json` database, preserving manual edits (such as custom in/out points or manually assigned MIDI notes).
- **`auto_assign_midi()`:** Automatically assigns sequential MIDI notes (starting from note 36 / C1) to all media files within a specified year.

### 3. `midi_handler.py` (MIDI Listening Thread)
Provides a QThread-based listener for MIDI input to avoid blocking the main PyQt UI thread.
- **`MidiListener`:** Connects to a specified MIDI port using `mido`. It continuously listens for `note_on` and `control_change` events.
- **Signals:** Emits PyQt signals (`note_on_signal` and `cc_signal`) which are intercepted by the UI components (like `InstallMode` and `SettingsWindow`) to trigger actions.

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
The interface for the `library.py` functions. It lets the operator select a folder to scan and allows triggering the auto-assignment of MIDI notes for specific years.

### 4. `install_mode.py` (Installation Mode)
The primary runtime environment for the exhibition.
- **Full Screen Canvas:** Creates a borderless, black, full-screen canvas.
- **MIDI Integration:** Starts the `MidiListener` thread on the configured port.
- **Event Handling:** 
  - On `note_on`, it checks the `config.json` library for the currently selected year. If the note matches a file, it asks the `PlayerEngine` to play it.
  - On `control_change`, if the CC matches a learned control (scale, X, Y), it calculates a new geometry for the last active video layer and updates its position/size dynamically.

## Data Flow (Live Playback)
1. User selects a year from the combobox in **Install Mode**.
2. User presses a key on the MIDI keyboard.
3. `MidiListener` (on a background thread) captures `note_on` and emits a PyQt signal to `InstallMode`.
4. `InstallMode` looks up the file associated with the note and year in `config.json`.
5. `InstallMode` calls `PlayerEngine.play_media()`.
6. `PlayerEngine` stops the oldest layer, sets a random size/position, and plays the new file.
7. User turns a knob on the MIDI keyboard.
8. `MidiListener` emits a `cc_signal`.
9. `InstallMode` matches the CC number with the learned settings and calls `set_geometry()` on the active `PlayerLayer`, immediately changing its size or position.
