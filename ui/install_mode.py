from PyQt5.QtWidgets import QWidget, QVBoxLayout, QComboBox, QHBoxLayout, QTextEdit, QPushButton
from PyQt5.QtCore import Qt
from core.player_engine import PlayerEngine
from core.config import load_config
from core.midi_handler import MidiListener

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
        
        # MIDI Setup
        self.midi_thread = None
        port = self.config.get("midi_input", "")
        if port:
            self.midi_thread = MidiListener(port)
            self.midi_thread.note_on_signal.connect(self.on_midi_note)
            self.midi_thread.cc_signal.connect(self.on_midi_cc)
            self.midi_thread.log_signal.connect(self.log_debug)
            self.midi_thread.start()
        else:
            self.log_debug("Aucun port MIDI configuré dans config.json")
            
    def log_debug(self, message):
        self.debug_log.append(message)
        scrollbar = self.debug_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
            
    def on_midi_note(self, note, velocity):
        import time
        now = time.time()
        if now - getattr(self, 'last_note_time', 0) < 0.3:
            self.log_debug(f"Action ignorée: anti-surcharge (note {note})")
            return
        
        year = self.year_combo.currentText()
        if not year: return
        
        media_list = self.config["years"].get(year, [])
        for media in media_list:
            if media.get("midi_note") == note:
                self.last_note_time = now
                self.log_debug(f"Action: Lecture de {media['filepath']} (In: {media.get('in_point', 0.0)})")
                self.engine.play_media(media["filepath"], media.get("in_point", 0.0))
                break
                
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
            
    def close_and_stop(self):
        if self.midi_thread:
            self.midi_thread.stop()
        if hasattr(self, 'engine'):
            self.engine.cleanup()
        self.close()
        
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_and_stop()
