import sys
import vlc
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QRect
import random

class PlayerLayer:
    def __init__(self, vlc_instance, parent_widget):
        self.widget = QWidget(parent_widget)
        self.widget.setStyleSheet("background-color: black;")
        self.player = vlc_instance.media_player_new()
        
        if sys.platform == "darwin":
            self.player.set_nsobject(int(self.widget.winId()))
        elif sys.platform.startswith("linux"):
            self.player.set_xwindow(int(self.widget.winId()))
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self.widget.winId()))
            
        self.widget.hide()
        self.media_path = None
        
    def play(self, filepath, in_point=0.0):
        self.media_path = filepath
        media = self.player.get_instance().media_new(filepath)
        media.add_option(f"start-time={in_point}")
        self.player.set_media(media)
        self.player.play()
        self.widget.show()
        
    def stop(self):
        self.player.stop()
        self.widget.hide()
        
    def set_geometry(self, x, y, w, h):
        self.widget.setGeometry(QRect(x, y, w, h))

class PlayerEngine:
    def __init__(self, parent_widget, num_layers=3):
        # On désactive l'accélération matérielle (--avcodec-hw=none) 
        # car VideoToolbox fait souvent planter VLC sur les anciens macOS.
        self.vlc_instance = vlc.Instance("--no-xlib", "--avcodec-hw=none")
        self.layers = [PlayerLayer(self.vlc_instance, parent_widget) for _ in range(num_layers)]
        self.current_layer_idx = 0
        self.parent_widget = parent_widget
        
    def play_media(self, filepath, in_point=0.0):
        # Round robin
        layer = self.layers[self.current_layer_idx]
        layer.stop()
        
        # Random position and scale
        parent_rect = self.parent_widget.rect()
        pw, ph = parent_rect.width(), parent_rect.height()
        
        scale = random.uniform(0.3, 0.7) # Random scale between 30% and 70% of screen
        w = int(pw * scale)
        h = int(ph * scale)
        
        x = random.randint(0, pw - w)
        y = random.randint(0, ph - h)
        
        layer.set_geometry(x, y, w, h)
        layer.play(filepath, in_point)
        
        # Raise to top so it's visible over older clips
        layer.widget.raise_()
        
        # Move to next layer
        self.current_layer_idx = (self.current_layer_idx + 1) % len(self.layers)

    def get_last_active_layer(self):
        idx = (self.current_layer_idx - 1) % len(self.layers)
        return self.layers[idx]
