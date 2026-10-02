from PyQt5.QtWidgets import QWidget, QVBoxLayout, QComboBox, QHBoxLayout, QTextEdit
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
        self.years = list(self.config.get("years", {}).keys())
        
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
        year = self.year_combo.currentText()
        if not year: return
        
        media_list = self.config["years"].get(year, [])
        for media in media_list:
            if media.get("midi_note") == note:
                self.log_debug(f"Action: Lecture de {media['filepath']} (In: {media.get('in_point', 0.0)})")
                self.engine.play_media(media["filepath"], media.get("in_point", 0.0))
                break
                
    def on_midi_cc(self, channel, control, value):
        cc_scale = self.config.get("cc_scale") or 74
        cc_pos_x = self.config.get("cc_pos_x") or 71
        cc_pos_y = self.config.get("cc_pos_y") or 72
        
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
        
        layer = self.engine.get_last_active_layer()
        if not layer or not layer.widget.isVisible():
            return
            
        rect = layer.widget.geometry()
        parent_rect = self.canvas.rect()
        
        if is_scale:
            scale = 0.1 + (value / 127.0) * 1.5
            cx = rect.x() + rect.width() / 2
            cy = rect.y() + rect.height() / 2
            w = int(parent_rect.width() * scale)
            h = int(parent_rect.height() * scale)
            layer.set_geometry(int(cx - w/2), int(cy - h/2), w, h)
            
        elif is_pos_x:
            x = int((value / 127.0) * (parent_rect.width() - rect.width()))
            layer.set_geometry(x, rect.y(), rect.width(), rect.height())
            
        elif is_pos_y:
            y = int((value / 127.0) * (parent_rect.height() - rect.height()))
            layer.set_geometry(rect.x(), y, rect.width(), rect.height())
            
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.midi_thread:
                self.midi_thread.stop()
            self.close()
