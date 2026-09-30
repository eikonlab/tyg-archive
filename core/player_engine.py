import sys
import os
import time
import vlc
from PyQt5.QtWidgets import QWidget, QLabel
from PyQt5.QtCore import QRect, QTimer, Qt
from PyQt5.QtGui import QPixmap
import random


# Extensions reconnues comme images (affichées via Qt, pas VLC)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
# Extensions reconnues comme vidéo/audio (affichées via VLC)
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v",
                    ".mpg", ".mpeg", ".wav", ".mp3", ".aac", ".flac", ".ogg"}


def _log(tag, msg):
    """Log avec timestamp pour le debug de performance."""
    ts = time.strftime("%H:%M:%S")
    ms = int((time.time() % 1) * 1000)
    print(f"[{ts}.{ms:03d}] [{tag}] {msg}")


def _file_info(filepath):
    """Retourne des infos utiles sur le fichier (taille, extension)."""
    try:
        stat = os.stat(filepath)
        size_mb = stat.st_size / (1024 * 1024)
        ext = os.path.splitext(filepath)[1].lower()
        return size_mb, ext
    except OSError as e:
        return -1, f"ERREUR: {e}"


def _read_speed_test(filepath, chunk_bytes=1024 * 512):
    """Lit un petit morceau du fichier pour estimer la vitesse du disque."""
    try:
        t0 = time.time()
        with open(filepath, "rb") as f:
            data = f.read(chunk_bytes)
        dt = time.time() - t0
        if dt > 0:
            speed_mb = (len(data) / (1024 * 1024)) / dt
            return len(data), dt, speed_mb
        return len(data), 0, float("inf")
    except OSError as e:
        return 0, 0, -1


def _is_image(filepath):
    """Vérifie si le fichier est une image."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in IMAGE_EXTENSIONS


class ImageLayer:
    """Couche d'affichage pour les images, utilise Qt QPixmap (rapide, pas de VLC)."""
    
    def __init__(self, parent_widget, layer_id=0):
        self.layer_id = layer_id
        self.label = QLabel(parent_widget)
        self.label.setStyleSheet("background-color: black;")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setScaledContents(True)
        self.label.hide()
        self.media_path = None
        self._play_request_time = None
        
    def play(self, filepath, max_w=1920, max_h=1080):
        tag = f"ImgLayer-{self.layer_id}"
        self._play_request_time = time.time()
        self.media_path = filepath
        
        basename = os.path.basename(filepath)
        _log(tag, f"🖼 IMAGE demandée: {basename}")
        
        t0 = time.time()
        pixmap = QPixmap(filepath)
        dt_load = (time.time() - t0) * 1000
        
        if pixmap.isNull():
            _log(tag, f"  ⚠ Impossible de charger l'image !")
            return
        
        orig_w, orig_h = pixmap.width(), pixmap.height()
        _log(tag, f"  Chargée en {dt_load:.0f} ms — {orig_w}x{orig_h}")
        
        # Réduire l'image à la taille d'affichage pour économiser la RAM
        if orig_w > max_w or orig_h > max_h:
            t0 = time.time()
            pixmap = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dt_scale = (time.time() - t0) * 1000
            _log(tag, f"  ↓ Réduite à {pixmap.width()}x{pixmap.height()} en {dt_scale:.0f} ms (économie RAM)")
        
        self.label.setPixmap(pixmap)
        self.label.show()
    
    def stop(self):
        if self.media_path:
            _log(f"ImgLayer-{self.layer_id}", f"⏹ STOP image: {os.path.basename(self.media_path)}")
        self.label.hide()
        self.label.clear()
        self.media_path = None
        
    def set_geometry(self, x, y, w, h):
        self.label.setGeometry(QRect(x, y, w, h))
        
    @property
    def widget(self):
        return self.label


class SingleVideoPlayer:
    """Un seul player VLC réutilisé pour toutes les vidéos.
    
    On évite de créer/détruire des players VLC car player.stop() 
    provoque un crash (SIGTERM) sur les vieux macOS (High Sierra).
    À la place, on change simplement le media du player existant.
    """
    
    def __init__(self, vlc_instance, parent_widget):
        self._widget = QWidget(parent_widget)
        self._widget.setStyleSheet("background-color: black;")
        self.player = vlc_instance.media_player_new()
        
        if sys.platform == "darwin":
            self.player.set_nsobject(int(self._widget.winId()))
        elif sys.platform.startswith("linux"):
            self.player.set_xwindow(int(self._widget.winId()))
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self._widget.winId()))
            
        self._widget.hide()
        self.media_path = None
        self._play_request_time = None
        
    def play(self, filepath, in_point=0.0):
        tag = "Video"
        self._play_request_time = time.time()
        
        # --- Info fichier ---
        size_mb, ext = _file_info(filepath)
        basename = os.path.basename(filepath)
        old_media = os.path.basename(self.media_path) if self.media_path else "aucun"
        _log(tag, f"▶ VIDEO demandée: {basename}")
        _log(tag, f"  (remplace: {old_media})")
        _log(tag, f"  Chemin complet: {filepath}")
        if size_mb >= 0:
            _log(tag, f"  Taille: {size_mb:.1f} MB | Extension: {ext}")
        else:
            _log(tag, f"  ⚠ Impossible de lire le fichier: {ext}")
            
        # --- Test vitesse lecture disque ---
        bytes_read, dt, speed_mb = _read_speed_test(filepath)
        if speed_mb > 0:
            _log(tag, f"  Vitesse lecture disque: {speed_mb:.1f} MB/s ({bytes_read/1024:.0f} KB en {dt*1000:.0f} ms)")
        elif speed_mb < 0:
            _log(tag, f"  ⚠ Erreur lecture disque !")
        
        self.media_path = filepath
        
        # --- Changement de media SANS stop() ---
        # On ne fait PAS player.stop(). On remplace directement le media.
        # VLC gère internalement la transition sans crash.
        t0 = time.time()
        media = self.player.get_instance().media_new(filepath)
        media.add_option(f"start-time={in_point}")
        media.add_option(":avcodec-hw=none")
        media.add_option(":no-videotoolbox")
        self.player.set_media(media)
        dt_media = (time.time() - t0) * 1000
        _log(tag, f"  Media VLC remplacé en {dt_media:.0f} ms (in_point={in_point})")
        
        # --- Lancement lecture ---
        t0 = time.time()
        self.player.play()
        dt_play = (time.time() - t0) * 1000
        _log(tag, f"  player.play() retourné en {dt_play:.0f} ms")
        
        self._widget.show()
        
    def hide(self):
        """Cache le widget vidéo sans appeler player.stop()."""
        self._widget.hide()
        
    def set_geometry(self, x, y, w, h):
        self._widget.setGeometry(QRect(x, y, w, h))

    @property
    def widget(self):
        return self._widget

    def check_playback_state(self):
        """Vérifie l'état du player VLC et logge les infos."""
        tag = "Video"
        state = self.player.get_state()
        state_names = {
            vlc.State.NothingSpecial: "NothingSpecial",
            vlc.State.Opening: "Opening",
            vlc.State.Buffering: "Buffering", 
            vlc.State.Playing: "Playing",
            vlc.State.Paused: "Paused",
            vlc.State.Stopped: "Stopped",
            vlc.State.Ended: "Ended",
            vlc.State.Error: "Error",
        }
        state_name = state_names.get(state, str(state))
        
        elapsed = ""
        if self._play_request_time:
            elapsed = f" (depuis play: {(time.time() - self._play_request_time)*1000:.0f} ms)"
        
        _log(tag, f"  État VLC: {state_name}{elapsed}")
        
        if state == vlc.State.Playing:
            media = self.player.get_media()
            if media:
                duration = self.player.get_length()
                position = self.player.get_time()
                _log(tag, f"  Position: {position} ms / {duration} ms")
                    
                vw = self.player.video_get_width()
                vh = self.player.video_get_height()
                if vw and vh:
                    _log(tag, f"  Résolution vidéo: {vw}x{vh}")
                    
                fps = self.player.get_fps()
                if fps:
                    _log(tag, f"  FPS: {fps:.1f}")
                    
            return True
        elif state == vlc.State.Error:
            _log(tag, f"  ❌ ERREUR VLC lors de la lecture !")
            return False
        
        return None


class PlayerEngine:
    NUM_IMAGE_LAYERS = 3
    
    def __init__(self, parent_widget):
        # VLC : désactivation de l'accélération matérielle.
        vlc_args = [
            "--no-xlib",
            "--avcodec-hw=none",
            "--no-videotoolbox",
            "--verbose=0",
        ]
        _log("Engine", f"Initialisation VLC avec args: {vlc_args}")
        self.vlc_instance = vlc.Instance(*vlc_args)
        
        # UN SEUL player vidéo VLC (réutilisé, jamais stop(), juste set_media)
        self.video_player = SingleVideoPlayer(self.vlc_instance, parent_widget)
        
        # Layers image (Qt, légers)
        self.image_layers = [ImageLayer(parent_widget, i) for i in range(self.NUM_IMAGE_LAYERS)]
        self.current_image_idx = 0
        self.parent_widget = parent_widget
        
        # Référence au dernier layer utilisé (pour les CC MIDI scale/pos)
        self._last_active_layer = None
        self._last_active_is_video = False
        
        _log("Engine", f"1 video player (réutilisé) + {self.NUM_IMAGE_LAYERS} image layers créés")
        _log("Engine", f"✅ Pas de player.stop() = pas de crash VLC")
        
        # Timer pour vérifier l'état du player VLC après un play
        self._state_check_timer = QTimer()
        self._state_check_timer.timeout.connect(self._check_states)
        self._pending_check_times = []
        
    def play_media(self, filepath, in_point=0.0):
        t0 = time.time()
        _log("Engine", "=" * 60)
        
        # Random position and scale
        parent_rect = self.parent_widget.rect()
        pw, ph = parent_rect.width(), parent_rect.height()
        
        scale = random.uniform(0.3, 0.7)
        w = int(pw * scale)
        h = int(ph * scale)
        x = random.randint(0, pw - w)
        y = random.randint(0, ph - h)
        
        if _is_image(filepath):
            # --- AFFICHAGE IMAGE via Qt ---
            _log("Engine", f"play_media() IMAGE — ImgLayer {self.current_image_idx}")
            layer = self.image_layers[self.current_image_idx]
            layer.stop()
            layer.set_geometry(x, y, w, h)
            layer.play(filepath)
            layer.widget.raise_()
            self._last_active_layer = layer
            self._last_active_is_video = False
            self.current_image_idx = (self.current_image_idx + 1) % len(self.image_layers)
        else:
            # --- LECTURE VIDEO via VLC (un seul player, réutilisé) ---
            _log("Engine", f"play_media() VIDEO")
            self.video_player.set_geometry(x, y, w, h)
            self.video_player.play(filepath, in_point)
            self.video_player.widget.raise_()
            self._last_active_layer = self.video_player
            self._last_active_is_video = True
            
            # Programmer des vérifications d'état
            self._pending_check_times = [200, 500, 1000, 2000, 5000]
            if not self._state_check_timer.isActive():
                self._state_check_timer.start(100)
        
        dt_total = (time.time() - t0) * 1000
        _log("Engine", f"play_media() terminé en {dt_total:.0f} ms")

    def _check_states(self):
        """Vérifie périodiquement l'état du player VLC."""
        if not self._pending_check_times:
            self._state_check_timer.stop()
            return
            
        if self.video_player._play_request_time is None:
            self._state_check_timer.stop()
            return
            
        now = time.time()
        elapsed_ms = (now - self.video_player._play_request_time) * 1000
        
        if elapsed_ms >= self._pending_check_times[0]:
            _log("Engine", f"--- Vérification état (après {self._pending_check_times[0]} ms) ---")
            self.video_player.check_playback_state()
            self._pending_check_times.pop(0)
            
        if not self._pending_check_times:
            self._state_check_timer.stop()

    def get_last_active_layer(self):
        return self._last_active_layer
