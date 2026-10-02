import sys
import os
import time
import tempfile
import vlc
from PyQt5.QtWidgets import QWidget, QLabel
from PyQt5.QtCore import QRect, QTimer, Qt
from PyQt5.QtGui import QPixmap
import random


# Extensions reconnues comme images (affichées via Qt, pas VLC)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}

# Nombre max de frames figées visibles à l'écran (mosaïque)
MAX_FROZEN_FRAMES = 12

# Intervalle de rafraîchissement du "live view" (ms)
# ~7 fps — suffisant pour du contenu SD dans une installation
LIVE_REFRESH_MS = 150


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
        self.label.raise_()
        
    def hide(self):
        self.label.hide()
        self.label.clear()
    
    def set_geometry(self, x, y, w, h):
        self.label.setGeometry(QRect(x, y, w, h))
        
    @property
    def widget(self):
        return self.label


class PlayerEngine:
    """Moteur de lecture.
    
    Architecture :
    - VLC tourne HORS ÉCRAN (widget caché à -5000,-5000) pour le décodage vidéo
    - Un QLabel "live_label" affiche la vidéo via des snapshots périodiques (~7fps)
    - Les frozen frames sont de simples QLabels
    - TOUT est rendu via Qt → pas de problème de z-order avec VLC sur macOS
    """
    
    def __init__(self, parent_widget):
        # VLC : désactivation de l'accélération matérielle
        vlc_args = [
            "--no-xlib",
            "--avcodec-hw=none",
            "--no-videotoolbox",
            "--verbose=0",
        ]
        _log("Engine", f"Initialisation VLC avec args: {vlc_args}")
        self.vlc_instance = vlc.Instance(*vlc_args)
        
        # Player VLC HORS ÉCRAN (pour le décodage uniquement)
        self._vlc_widget = QWidget(parent_widget)
        self._vlc_widget.setGeometry(-5000, -5000, 720, 576)
        self._vlc_widget.show()  # Doit être "visible" pour que VLC rende
        self.player = self.vlc_instance.media_player_new()
        
        if sys.platform == "darwin":
            self.player.set_nsobject(int(self._vlc_widget.winId()))
        elif sys.platform.startswith("linux"):
            self.player.set_xwindow(int(self._vlc_widget.winId()))
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self._vlc_widget.winId()))
        
        self.media_path = None
        self._play_request_time = None
        
        # QLabel "live" : affiche la vidéo en cours via snapshots Qt
        self.live_label = QLabel(parent_widget)
        self.live_label.setStyleSheet("background-color: black;")
        self.live_label.setScaledContents(True)
        self.live_label.hide()
        
        # Pool de frames figées (mosaïque)
        self.frozen_frames = [FrozenFrame(parent_widget, i) for i in range(MAX_FROZEN_FRAMES)]
        self.current_frozen_idx = 0
        
        self.parent_widget = parent_widget
        self._last_active_layer = None
        
        # Dossier temporaire pour les snapshots VLC
        self._snap_dir = tempfile.mkdtemp(prefix="tyg_snap_")
        self._snap_counter = 0
        
        # Timer pour rafraîchir le "live view" avec des snapshots VLC
        self._live_timer = QTimer()
        self._live_timer.timeout.connect(self._refresh_live)
        self._is_video_playing = False
        
        # Timer pour vérifier l'état VLC
        self._state_check_timer = QTimer()
        self._state_check_timer.timeout.connect(self._check_states)
        self._pending_check_times = []
        
        _log("Engine", f"VLC hors écran + {MAX_FROZEN_FRAMES} frozen frames")
        _log("Engine", f"✅ Tout rendu via Qt (pas de surface VLC visible)")
        _log("Engine", f"   Live refresh: {LIVE_REFRESH_MS}ms (~{1000//LIVE_REFRESH_MS} fps)")
        
    def _take_snapshot(self):
        """Capture une frame VLC et la retourne comme QPixmap."""
        state = self.player.get_state()
        if state not in (vlc.State.Playing, vlc.State.Paused):
            return None
        
        self._snap_counter += 1
        snap_path = os.path.join(self._snap_dir, f"snap_{self._snap_counter}.png")
        
        result = self.player.video_take_snapshot(0, snap_path, 0, 0)
        if result != 0:
            return None
        
        # Attendre que le fichier soit écrit
        for _ in range(15):
            if os.path.exists(snap_path) and os.path.getsize(snap_path) > 0:
                break
            time.sleep(0.01)
        
        if not os.path.exists(snap_path) or os.path.getsize(snap_path) == 0:
            return None
            
        pixmap = QPixmap(snap_path)
        
        try:
            os.remove(snap_path)
        except OSError:
            pass
        
        if pixmap.isNull():
            return None
            
        return pixmap
    
    def _refresh_live(self):
        """Rafraîchit le QLabel live avec un snapshot VLC."""
        if not self._is_video_playing:
            return
            
        pixmap = self._take_snapshot()
        if pixmap is not None:
            self.live_label.setPixmap(pixmap)
            if not self.live_label.isVisible():
                self.live_label.show()
    
    def _freeze_live(self):
        """Fige le contenu actuel du live_label comme frozen frame."""
        if not self.live_label.isVisible():
            return
            
        pixmap = self.live_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return
            
        geometry = self.live_label.geometry()
        frozen = self.frozen_frames[self.current_frozen_idx]
        frozen.show_pixmap(pixmap, geometry)
        
        _log("Engine", f"  ❄ Frame figée → FrozenFrame-{self.current_frozen_idx} ({geometry.width()}x{geometry.height()})")
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
            # --- AFFICHAGE IMAGE ---
            _log("Engine", f"play_media() IMAGE")
            
            # Figer le live actuel s'il est visible
            self._freeze_live()
            
            # Stop any running video so it doesn't keep refreshing and popping to the front
            self._is_video_playing = False
            if self.player.get_state() != vlc.State.Stopped:
                self.player.stop()
            self.live_label.hide()
            
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
                
                if orig_w > 1920 or orig_h > 1080:
                    pixmap = pixmap.scaled(1920, 1080, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    _log("Engine", f"  ↓ Réduite à {pixmap.width()}x{pixmap.height()}")
                
                frozen = self.frozen_frames[self.current_frozen_idx]
                frozen.show_pixmap(pixmap, QRect(x, y, w, h))
                self._last_active_layer = frozen
                
                _log("Engine", f"  → FrozenFrame-{self.current_frozen_idx}")
                self.current_frozen_idx = (self.current_frozen_idx + 1) % len(self.frozen_frames)
            
        else:
            # --- LECTURE VIDEO ---
            _log("Engine", f"play_media() VIDEO")
            
            # 1. Figer le live actuel
            self._freeze_live()
            
            # 2. Info fichier
            size_mb, ext = _file_info(filepath)
            basename = os.path.basename(filepath)
            old_media = os.path.basename(self.media_path) if self.media_path else "aucun"
            _log("Engine", f"  ▶ {basename}")
            _log("Engine", f"    (remplace: {old_media})")
            if size_mb >= 0:
                _log("Engine", f"    Taille: {size_mb:.1f} MB | Extension: {ext}")
            
            # Test vitesse disque
            bytes_read, dt, speed_mb = _read_speed_test(filepath)
            if speed_mb > 0:
                _log("Engine", f"    Disque: {speed_mb:.1f} MB/s")
            
            self.media_path = filepath
            
            # 3. Changer le media VLC (pas de stop!)
            media = self.player.get_instance().media_new(filepath)
            media.add_option(f"start-time={in_point}")
            media.add_option(":avcodec-hw=none")
            media.add_option(":no-videotoolbox")
            self.player.set_media(media)
            self.player.play()
            self._play_request_time = time.time()
            self._is_video_playing = True
            
            # 4. Positionner le live_label à l'endroit voulu
            self.live_label.setGeometry(QRect(x, y, w, h))
            self.live_label.setStyleSheet("background-color: black;")
            self.live_label.show()
            self.live_label.raise_()
            self._last_active_layer = self
            
            # 5. Démarrer le timer de rafraîchissement live
            if not self._live_timer.isActive():
                self._live_timer.start(LIVE_REFRESH_MS)
            
            # Programmer des vérifications d'état
            self._pending_check_times = [500, 1000, 3000]
            if not self._state_check_timer.isActive():
                self._state_check_timer.start(100)
        
        dt_total = (time.time() - t0) * 1000
        _log("Engine", f"play_media() terminé en {dt_total:.0f} ms")

    def _check_states(self):
        """Vérifie périodiquement l'état du player VLC."""
        if not self._pending_check_times:
            self._state_check_timer.stop()
            return
            
        if self._play_request_time is None:
            self._state_check_timer.stop()
            return
            
        now = time.time()
        elapsed_ms = (now - self._play_request_time) * 1000
        
        if elapsed_ms >= self._pending_check_times[0]:
            tag = "Engine"
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
            _log(tag, f"--- État VLC: {state_name} (après {self._pending_check_times[0]} ms) ---")
            
            if state == vlc.State.Playing:
                vw = self.player.video_get_width()
                vh = self.player.video_get_height()
                fps = self.player.get_fps()
                if vw and vh:
                    _log(tag, f"    {vw}x{vh} @ {fps:.0f}fps")
            
            self._pending_check_times.pop(0)
            
        if not self._pending_check_times:
            self._state_check_timer.stop()

    # --- Interface pour les CC MIDI (scale/position) ---
    
    @property
    def widget(self):
        """Pour la compatibilité avec le CC handler d'install_mode."""
        return self.live_label
    
    def set_geometry(self, x, y, w, h):
        """Pour la compatibilité avec le CC handler d'install_mode."""
        self.live_label.setGeometry(QRect(x, y, w, h))

    def get_last_active_layer(self):
        return self._last_active_layer
