import time
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QComboBox, QHBoxLayout, QTextEdit, QPushButton, QApplication
from PyQt5.QtCore import Qt, QTimer
from core.player_engine import PlayerEngine
from core.config import load_config
from core.midi_handler import MidiListener
from ui.year_hud import YearHUDOverlay

class InstallMode(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Installation Mode")
        self.showFullScreen()
        self.setStyleSheet("background-color: black; color: white;")
        
        self.config = load_config()
        self.years = sorted(list(self.config.get("years", {}).keys()))
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Top bar for operator
        top_bar = QHBoxLayout()
        self.year_combo = QComboBox()
        self.year_combo.addItems(self.years)
        self.year_combo.setMinimumWidth(150)
        self.year_combo.currentIndexChanged.connect(self._on_year_changed)
        self.year_combo.setStyleSheet("""
            QComboBox {
                background-color: #333; 
                font-size: 20px; 
                padding: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                selection-background-color: #555;
            }
        """)
        top_bar.addWidget(self.year_combo)
        top_bar.addStretch()
        
        self.quit_btn = QPushButton("Quitter")
        self.quit_btn.setStyleSheet("""
            QPushButton {
                background-color: #aa0000;
                color: white;
                font-size: 16px;
                padding: 8px 15px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #ff0000;
            }
        """)
        self.quit_btn.clicked.connect(self.close_and_stop)
        top_bar.addWidget(self.quit_btn)
        
        layout.addLayout(top_bar)
        
        self.canvas = QWidget()
        layout.addWidget(self.canvas, 1)
        
        self.debug_log = QTextEdit()
        self.debug_log.setReadOnly(True)
        self.debug_log.setStyleSheet("background-color: rgba(0, 0, 0, 150); color: #0f0; font-family: monospace;")
        self.debug_log.setMaximumHeight(150)
        layout.addWidget(self.debug_log)
        
        self.setLayout(layout)
        
        self.engine = PlayerEngine(self.canvas)

        # Overlay HUD pour le nom du dossier / année
        self.year_hud = YearHUDOverlay(self)
        self.year_hud.setGeometry(self.rect())

        # Paramètres d'accélération progressive de la pitchwheel
        self.PITCH_DEADZONE = 1200       # Zone morte pour éviter tout faux déclenchement au repos
        self.PITCH_INITIAL_DELAY = 0.38  # Délai initial (380ms) avant le début de la répétition
        self.PITCH_RAMP_UP_TIME = 2.2   # Temps pour atteindre la cadence maximale
        self.PITCH_MAX_INTERVAL = 0.35  # Intervalle lent (350ms par cran)
        self.PITCH_MIN_INTERVAL = 0.06  # Intervalle rapide (60ms par cran)

        self._pitch_active = False
        self._pitch_dir = 0
        self._pitch_val = 0
        self._pitch_start_time = 0.0
        self._pitch_last_step_time = 0.0

        self._pitch_timer = QTimer(self)
        self._pitch_timer.setInterval(16)  # ~60 Hz pour évaluation fluide
        self._pitch_timer.timeout.connect(self._on_pitch_tick)
        
        # MIDI Setup
        self.midi_thread = None
        port = self.config.get("midi_input", "")
        if port:
            self.midi_thread = MidiListener(port)
            self.midi_thread.note_on_signal.connect(self.on_midi_note_on)
            self.midi_thread.note_off_signal.connect(self.on_midi_note_off)
            self.midi_thread.cc_signal.connect(self.on_midi_cc)
            self.midi_thread.pitchwheel_signal.connect(self.on_midi_pitchwheel)
            self.midi_thread.log_signal.connect(self.log_debug)
            self.midi_thread.start()
        else:
            self.log_debug("Aucun port MIDI configuré dans config.json")
            
    def log_debug(self, message):
        self.debug_log.append(message)
        scrollbar = self.debug_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
            
    def _on_year_changed(self):
        year = self.year_combo.currentText()
        self.log_debug(f"Année sélectionnée: {year}")
        if hasattr(self, 'engine'):
            for slot in self.engine.slots:
                if slot.is_active:
                    slot.stop()
            self.engine.active_voice_order.clear()
            self.engine._update_audio_volumes()
        if hasattr(self, 'year_hud') and self.year_hud:
            self.year_hud.display_year(year)
            self.year_hud.raise_()
            if not getattr(self, '_pitch_active', False):
                self.year_hud.release_pitchwheel()

    def on_midi_note_on(self, note, velocity):
        import time
        now = time.time()
        last_notes = getattr(self, '_last_note_times', {})
        if note in last_notes and (now - last_notes[note]) < 0.05:
            return  # Anti-rebond par note individuelle (< 50ms)
        last_notes[note] = now
        self._last_note_times = last_notes
        
        year = self.year_combo.currentText()
        if not year:
            return
        
        media_list = self.config.get("years", {}).get(year, [])
        found = False
        for media in media_list:
            if media.get("midi_note") == note:
                found = True
                self.log_debug(f"Action: Note On {note} -> {media['filepath']} (In: {media.get('in_point', 0.0)}, Out: {media.get('out_point', 0.0)})")
                self.engine.trigger_note(
                    note,
                    media["filepath"], 
                    media.get("in_point", 0.0),
                    media.get("out_point", 0.0),
                    media.get("width", 0),
                    media.get("height", 0),
                    velocity
                )
                break
        if not found:
            self.log_debug(f"Note {note} reçue (Vel: {velocity}) mais aucun média assigné pour l'année {year}")

    def on_midi_note_off(self, note):
        self.log_debug(f"Action: Note Off {note}")
        self.engine.release_note(note)

    # Alias pour compatibilité
    on_midi_note = on_midi_note_on
                
    def on_midi_cc(self, channel, control, value):
        cc_scale = self.config.get("cc_scale") or 74
        cc_pos_x = self.config.get("cc_pos_x") or 71
        cc_pos_y = self.config.get("cc_pos_y") or 72
        cc_folder = self.config.get("cc_folder")
        
        sig = f"{channel}:{control}"
        
        # Retro-compatibilité : si la config a stocké un entier (ancienne version)
        if isinstance(cc_scale, int):
            is_scale = (control == cc_scale)
        else:
            is_scale = (sig == cc_scale)
            
        if isinstance(cc_pos_x, int):
            is_pos_x = (control == cc_pos_x)
        else:
            is_pos_x = (sig == cc_pos_x)
            
        if isinstance(cc_pos_y, int):
            is_pos_y = (control == cc_pos_y)
        else:
            is_pos_y = (sig == cc_pos_y)
            
        if isinstance(cc_folder, int):
            is_folder = (control == cc_folder)
        else:
            is_folder = (sig == cc_folder)
            
        if is_folder and len(self.years) > 0:
            # Map 0-127 to 0-(len-1)
            index = int((value / 127.0) * (len(self.years) - 1))
            self.year_combo.setCurrentIndex(index)
            return
        
        layer = self.engine.get_last_active_layer()
        if not layer or not layer.widget.isVisible():
            return
            
        rect = layer.widget.geometry()
        parent_rect = self.canvas.rect()
        
        # --- Optimisation de l'effet d'image rémanente (ghosting) ---
        import time
        now = time.time()
        last_g_time = getattr(self, 'last_ghost_time', 0)
        last_g_pos = getattr(self, 'last_ghost_pos', (0, 0, 0, 0))
        
        dx = abs(rect.x() - last_g_pos[0])
        dy = abs(rect.y() - last_g_pos[1])
        dw = abs(rect.width() - last_g_pos[2])
        
        moved_enough = dx > 40 or dy > 40 or dw > 40
        time_enough = (now - last_g_time) > 0.15 # 150ms intervalle minimum
        
        # Figer avant de déplacer si les conditions sont remplies
        if moved_enough and time_enough:
            self.engine.leave_ghost()
            self.last_ghost_time = now
            self.last_ghost_pos = (rect.x(), rect.y(), rect.width(), rect.height())
        # -------------------------------------------------------------
        
        if is_scale:
            scale = 0.1 + (value / 127.0) * 1.5
            cx = rect.x() + rect.width() / 2
            cy = rect.y() + rect.height() / 2
            aspect = rect.width() / float(rect.height()) if rect.height() > 0 else 1.0
            w = int(parent_rect.width() * scale)
            h = int(w / aspect)
            layer.set_geometry(int(cx - w/2), int(cy - h/2), w, h)
            
        elif is_pos_x:
            x = int((value / 127.0) * (parent_rect.width() - rect.width()))
            layer.set_geometry(x, rect.y(), rect.width(), rect.height())
            
        elif is_pos_y:
            y = int((value / 127.0) * (parent_rect.height() - rect.height()))
            layer.set_geometry(rect.x(), y, rect.width(), rect.height())
            
    def on_midi_pitchwheel(self, channel, pitch):
        if abs(pitch) < self.PITCH_DEADZONE:
            if self._pitch_active:
                self._pitch_active = False
                self._pitch_timer.stop()
                if hasattr(self, 'year_hud') and self.year_hud:
                    self.year_hud.release_pitchwheel()
            return

        # Pitchwheel vers le HAUT (positif) = Dossier suivant (ex: 2021 -> 2022)
        # Pitchwheel vers le BAS (négatif) = Dossier précédent (ex: 2022 -> 2021)
        direction = 1 if pitch > 0 else -1

        if not self._pitch_active or direction != self._pitch_dir:
            self._pitch_active = True
            self._pitch_dir = direction
            self._pitch_val = pitch
            now = time.time()
            self._pitch_start_time = now
            self._pitch_last_step_time = now
            if hasattr(self, 'year_hud') and self.year_hud:
                self.year_hud.cancel_fade()
            # Déclenchement immédiat du premier cran (facile pour monter/descendre d'un seul cran)
            self.step_year(direction)
            if not self._pitch_timer.isActive():
                self._pitch_timer.start()
        else:
            # Maintenu dans la même direction : mise à jour de la déflexion pour l'accélération
            self._pitch_val = pitch

    def _on_pitch_tick(self):
        if not self._pitch_active:
            self._pitch_timer.stop()
            return

        now = time.time()
        elapsed = now - self._pitch_start_time
        if elapsed < self.PITCH_INITIAL_DELAY:
            return  # Période de grâce pour permettre un seul cran facilement

        # Intensité de déflexion (0.0 à 1.0)
        deflection = max(0.0, min(1.0, (abs(self._pitch_val) - self.PITCH_DEADZONE) / (8191.0 - self.PITCH_DEADZONE)))
        # Progression temporelle pour l'accélération progressive (0.0 à 1.0)
        time_progress = min(1.0, (elapsed - self.PITCH_INITIAL_DELAY) / self.PITCH_RAMP_UP_TIME)

        speed_factor = deflection * (0.2 + 0.8 * (time_progress ** 1.3))
        speed_factor = max(0.0, min(1.0, speed_factor))
        interval = self.PITCH_MAX_INTERVAL - speed_factor * (self.PITCH_MAX_INTERVAL - self.PITCH_MIN_INTERVAL)

        if (now - self._pitch_last_step_time) >= interval:
            self._pitch_last_step_time = now
            self.step_year(self._pitch_dir)

    def step_year(self, direction):
        if not self.years:
            return
        count = len(self.years)
        current_idx = self.year_combo.currentIndex()
        if current_idx < 0:
            current_idx = 0
        # Boucle circulaire infinie
        new_idx = (current_idx + direction) % count
        self.year_combo.setCurrentIndex(new_idx)
        new_year = self.year_combo.currentText()
        if hasattr(self, 'year_hud') and self.year_hud:
            self.year_hud.display_year(new_year)
            self.year_hud.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'year_hud') and self.year_hud:
            self.year_hud.setGeometry(self.rect())
            self.year_hud.raise_()

    def close_and_stop(self):
        if hasattr(self, '_pitch_timer') and self._pitch_timer:
            self._pitch_timer.stop()
        if self.midi_thread:
            self.midi_thread.stop()
            self.midi_thread = None
        if hasattr(self, 'engine'):
            self.engine.cleanup()
        self.close()

    def closeEvent(self, event):
        self.close_and_stop()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_and_stop()
        elif event.key() in (Qt.Key_Right, Qt.Key_Up):
            self.step_year(1)
            if hasattr(self, 'year_hud') and self.year_hud:
                self.year_hud.release_pitchwheel()
        elif event.key() in (Qt.Key_Left, Qt.Key_Down):
            self.step_year(-1)
            if hasattr(self, 'year_hud') and self.year_hud:
                self.year_hud.release_pitchwheel()
