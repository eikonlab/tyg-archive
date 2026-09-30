import sys
import os
import time
import vlc
from PyQt5.QtWidgets import QWidget, QLabel
from PyQt5.QtCore import QRect, QTimer, Qt
from PyQt5.QtGui import QPixmap, QScreen
import random


# Extensions reconnues comme images (affichées via Qt, pas VLC)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
# Extensions reconnues comme vidéo/audio (affichées via VLC)
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v",
                    ".mpg", ".mpeg", ".wav", ".mp3", ".aac", ".flac", ".ogg"}

# Nombre max de frames figées visibles à l'écran (mosaïque)
MAX_FROZEN_FRAMES = 20


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


class FrozenFrame:
    """Un QLabel qui affiche une frame figée (screenshot d'une vidéo ou image)."""
    
    def __init__(self, parent_widget, frame_id=0):
        self.frame_id = frame_id
        self.label = QLabel(parent_widget)
        self.label.setStyleSheet("background-color: black;")
        self.label.setScaledContents(True)
        self.label.hide()
        
    def show_pixmap(self, pixmap, geometry):
        """Affiche un pixmap figé à la position donnée."""
        self.label.setGeometry(geometry)
        self.label.setPixmap(pixmap)
        self.label.show()
        
    def hide(self):
        self.label.hide()
        self.label.clear()
    
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
        self._parent_widget = parent_widget
        
    def grab_frame(self):
        """Capture la frame actuelle du widget VLC comme QPixmap."""
        if not self._widget.isVisible():
            return None
        # grab() capture le contenu rendu du widget
        pixmap = self._widget.grab()
        if pixmap.isNull():
            return None
        return pixmap
        
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
        
        # Pool de frames figées (mosaïque de screenshots)
        self.frozen_frames = [FrozenFrame(parent_widget, i) for i in range(MAX_FROZEN_FRAMES)]
        self.current_frozen_idx = 0
        
        self.parent_widget = parent_widget
        
        # Référence au dernier layer utilisé (pour les CC MIDI scale/pos)
        self._last_active_layer = None
        self._last_active_is_video = False
        
        _log("Engine", f"1 video player + {MAX_FROZEN_FRAMES} frozen frames créés")
        _log("Engine", f"✅ Mosaïque: chaque nouveau clip fige l'ancien en image statique")
        
        # Timer pour vérifier l'état du player VLC après un play
        self._state_check_timer = QTimer()
        self._state_check_timer.timeout.connect(self._check_states)
        self._pending_check_times = []
        
    def _freeze_current_video(self):
        """Capture la frame actuelle de la vidéo et la fige comme image statique."""
        if not self.video_player.widget.isVisible():
            return
            
        pixmap = self.video_player.grab_frame()
        if pixmap is None or pixmap.isNull():
            _log("Engine", "  ❄ Pas de frame à figer (widget vide)")
            return
            
        # Récupérer la géométrie actuelle du player vidéo
        geometry = self.video_player.widget.geometry()
        
        # Placer la frame figée dans le pool (round-robin)
        frozen = self.frozen_frames[self.current_frozen_idx]
        frozen.show_pixmap(pixmap, geometry)
        
        _log("Engine", f"  ❄ Frame figée → FrozenFrame-{self.current_frozen_idx} ({geometry.width()}x{geometry.height()})")
        
        self.current_frozen_idx = (self.current_frozen_idx + 1) % len(self.frozen_frames)
        
    def _freeze_current_image(self, image_layer):
        """Fige l'image actuelle en tant que frozen frame pour libérer l'ImageLayer."""
        if not image_layer.widget.isVisible() or not image_layer.media_path:
            return
            
        pixmap = image_layer.label.pixmap()
        if pixmap is None or pixmap.isNull():
            return
            
        geometry = image_layer.widget.geometry()
        frozen = self.frozen_frames[self.current_frozen_idx]
        frozen.show_pixmap(pixmap, geometry)
        
        _log("Engine", f"  ❄ Image figée → FrozenFrame-{self.current_frozen_idx}")
        self.current_frozen_idx = (self.current_frozen_idx + 1) % len(self.frozen_frames)
        
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
            _log("Engine", f"play_media() IMAGE")
            
            # Figer la vidéo en cours si visible
            self._freeze_current_video()
            
            # Créer un frozen frame directement pour l'image
            basename = os.path.basename(filepath)
            _log("Engine", f"  🖼 Chargement: {basename}")
            
            t_load = time.time()
            pixmap = QPixmap(filepath)
            dt_load = (time.time() - t_load) * 1000
            
            if pixmap.isNull():
                _log("Engine", f"  ⚠ Impossible de charger l'image !")
            else:
                orig_w, orig_h = pixmap.width(), pixmap.height()
                _log("Engine", f"  Chargée en {dt_load:.0f} ms — {orig_w}x{orig_h}")
                
                # Réduire pour économiser la RAM
                if orig_w > 1920 or orig_h > 1080:
                    pixmap = pixmap.scaled(1920, 1080, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    _log("Engine", f"  ↓ Réduite à {pixmap.width()}x{pixmap.height()}")
                
                # Placer dans le pool de frozen frames
                frozen = self.frozen_frames[self.current_frozen_idx]
                frozen.show_pixmap(pixmap, QRect(x, y, w, h))
                frozen.label.raise_()
                self._last_active_layer = frozen
                self._last_active_is_video = False
                
                _log("Engine", f"  → FrozenFrame-{self.current_frozen_idx}")
                self.current_frozen_idx = (self.current_frozen_idx + 1) % len(self.frozen_frames)
            
        else:
            # --- LECTURE VIDEO via VLC ---
            _log("Engine", f"play_media() VIDEO")
            
            # 1. Figer la frame actuelle de la vidéo en cours
            self._freeze_current_video()
            
            # 2. Déplacer le player VLC à la nouvelle position et jouer le nouveau clip
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
