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

# Extensions reconnues comme audio pur (jouées via VLC sans affichage)
AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff"}

# Nombre maximum de voix simultanées (1 = monophonique, optimisé pour Mac Mini)
MAX_VOICES = 1

# Nombre max de frames figées visibles à l'écran (mosaïque / ghosting)
MAX_FROZEN_FRAMES = 12

# Intervalle de rafraîchissement du "live view" (ms)
# ~8 fps — fluide et léger pour 3 voix en simultané
LIVE_REFRESH_MS = 120


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


def _is_image(filepath):
    """Vérifie si le fichier est une image."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in IMAGE_EXTENSIONS


def _is_audio(filepath):
    """Vérifie si le fichier est un fichier audio pur."""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in AUDIO_EXTENSIONS


class FrozenFrame:
    """Un QLabel qui affiche une frame figée (mosaïque d'arrière-plan)."""
    
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
        self.label.lower()  # Toujours sous les clips actifs
        
    def hide(self):
        self.label.hide()
        self.label.clear()
    
    def set_geometry(self, x, y, w, h):
        self.label.setGeometry(QRect(x, y, w, h))
        
    @property
    def widget(self):
        return self.label


class VoiceSlot:
    """Un slot polyphonique (voix) capable de jouer une vidéo, une image ou un audio."""
    
    def __init__(self, vlc_instance, parent_widget, slot_id=0):
        self.slot_id = slot_id
        self.vlc_instance = vlc_instance
        self.parent_widget = parent_widget
        
        # Player VLC HORS ÉCRAN (décocage logiciel pour éviter les conflits z-order Cocoa)
        self._vlc_widget = QWidget(parent_widget)
        self._vlc_widget.setGeometry(-5000 - slot_id * 1000, -5000, 720, 576)
        self._vlc_widget.show()
        
        self.player = self.vlc_instance.media_player_new()
        if sys.platform == "darwin":
            self.player.set_nsobject(int(self._vlc_widget.winId()))
        elif sys.platform.startswith("linux"):
            self.player.set_xwindow(int(self._vlc_widget.winId()))
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self._vlc_widget.winId()))
            
        # QLabel live affiché sur le canevas
        self.live_label = QLabel(parent_widget)
        self.live_label.setStyleSheet("background-color: black;")
        self.live_label.setScaledContents(True)
        self.live_label.hide()
        
        # État
        self.is_active = False
        self.note = None
        self.media_path = None
        self.media_type = None  # "video", "image", "audio"
        self.in_point = 0.0
        self.out_point = 0.0
        self.is_paused_on_out = False
        self.play_request_time = None
        self.video_aspect_adjusted = False
        self.aspect_ratio = 16 / 9
        
    def play_video(self, filepath, in_point=0.0, out_point=0.0, geometry=None):
        """Lance la lecture d'une vidéo dans ce slot."""
        self.stop_playback_only()
        
        self.media_path = filepath
        self.media_type = "video"
        self.in_point = in_point
        self.out_point = out_point
        self.is_paused_on_out = False
        self.video_aspect_adjusted = False
        self.play_request_time = time.time()
        self.is_active = True
        
        # Préparation VLC
        media = self.vlc_instance.media_new(filepath)
        if in_point > 0.0:
            media.add_option(f"start-time={in_point}")
        media.add_option(":avcodec-hw=none")
        media.add_option(":no-videotoolbox")
        self.player.set_media(media)
        self.player.play()
        
        # Affichage du label Qt
        if geometry:
            self.live_label.setGeometry(geometry)
        self.live_label.setStyleSheet("background-color: black;")
        self.live_label.show()
        self.live_label.raise_()
        
        _log(f"Slot-{self.slot_id}", f"▶ Play VIDEO: {os.path.basename(filepath)} (IN={in_point}s, OUT={out_point}s)")

    def play_image(self, filepath, geometry=None):
        """Affiche une image fixe dans ce slot."""
        self.stop_playback_only()
        
        self.media_path = filepath
        self.media_type = "image"
        self.in_point = 0.0
        self.out_point = 0.0
        self.is_paused_on_out = False
        self.play_request_time = time.time()
        self.is_active = True
        
        pixmap = QPixmap(filepath)
        if pixmap.isNull():
            _log(f"Slot-{self.slot_id}", f"⚠ Erreur chargement image {filepath}")
            self.stop()
            return
            
        orig_w, orig_h = pixmap.width(), pixmap.height()
        if orig_w > 1920 or orig_h > 1080:
            pixmap = pixmap.scaled(1920, 1080, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
        if geometry:
            parent_rect = self.parent_widget.rect()
            pw, ph = parent_rect.width(), parent_rect.height()
            if orig_h > 0:
                aspect = orig_w / orig_h
                w = geometry.width()
                h = int(w / aspect)
                if h > ph:
                    h = ph
                    w = int(h * aspect)
                x = min(geometry.x(), max(0, pw - w))
                y = min(geometry.y(), max(0, ph - h))
                self.live_label.setGeometry(QRect(x, y, w, h))
            else:
                self.live_label.setGeometry(geometry)
                
        self.live_label.setPixmap(pixmap)
        self.live_label.show()
        self.live_label.raise_()
        _log(f"Slot-{self.slot_id}", f"🖼 Affichage IMAGE: {os.path.basename(filepath)}")

    def play_audio(self, filepath, in_point=0.0, out_point=0.0):
        """Joue un fichier audio pur via VLC."""
        self.stop_playback_only()
        
        self.media_path = filepath
        self.media_type = "audio"
        self.in_point = in_point
        self.out_point = out_point
        self.is_paused_on_out = False
        self.play_request_time = time.time()
        self.is_active = True
        
        self.live_label.hide()
        
        media = self.vlc_instance.media_new(filepath)
        if in_point > 0.0:
            media.add_option(f"start-time={in_point}")
        self.player.set_media(media)
        self.player.play()
        _log(f"Slot-{self.slot_id}", f"🎵 Play AUDIO: {os.path.basename(filepath)}")

    def pause_on_out(self):
        """Fige la vidéo sur sa frame courante (atteinte du OUT point)."""
        if self.is_paused_on_out:
            return
        self.is_paused_on_out = True
        if self.media_type == "video":
            self.player.pause()
            _log(f"Slot-{self.slot_id}", f"⏸ Pause sur OUT-point atteint ({self.out_point}s)")

    def set_volume(self, volume_percent):
        """Règle le volume VLC (0 à 100)."""
        vol = max(0, min(100, int(volume_percent)))
        self.player.audio_set_volume(vol)

    def stop_playback_only(self):
        """Arrête le moteur VLC sans modifier la géométrie."""
        if self.player.get_state() != vlc.State.Stopped:
            self.player.stop()

    def stop(self):
        """Arrêt complet de ce slot (relâchement de touche ou vol de voix)."""
        self.stop_playback_only()
        self.live_label.hide()
        self.live_label.clear()
        self.is_active = False
        self.note = None
        self.media_path = None
        self.media_type = None
        self.is_paused_on_out = False
        self.video_aspect_adjusted = False
        _log(f"Slot-{self.slot_id}", f"⏹ Slot libéré et éteint")

    def take_snapshot(self, snap_dir, counter):
        """Prend un snapshot VLC pour rafraîchir le live_label."""
        state = self.player.get_state()
        if state not in (vlc.State.Playing, vlc.State.Paused):
            return None
            
        snap_path = os.path.join(snap_dir, f"snap_{self.slot_id}_{counter}.png")
        res = self.player.video_take_snapshot(0, snap_path, 0, 0)
        if res != 0:
            return None
            
        # Courte attente non bloquante de fichier (max 25ms)
        for _ in range(5):
            if os.path.exists(snap_path) and os.path.getsize(snap_path) > 0:
                break
            time.sleep(0.005)
            
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

    # Interface de compatibilité CC (scale / position X/Y)
    @property
    def widget(self):
        return self.live_label

    def set_geometry(self, x, y, w, h):
        self.live_label.setGeometry(QRect(x, y, w, h))

    def cleanup(self):
        self.stop()
        if hasattr(self, 'player') and self.player:
            self.player.release()
            self.player = None


class PlayerEngine:
    """Moteur de lecture monophonique (1 seule voix active, priorité à la dernière note).
    
    Architecture :
    - 1 slot de voix (VoiceSlot) optimisé pour préserver le CPU/GPU sur Mac Mini
    - Décodage VLC hors-écran
    - Affichage 100% Qt (QLabel) pour éviter les conflits z-order sous macOS
    - Rafraîchissement live cadencé par QTimer
    - Priorité à la dernière note enfoncée (Hold-to-Play monophonique)
    """
    
    def __init__(self, parent_widget):
        self.parent_widget = parent_widget
        
        # Initialisation VLC
        vlc_args = [
            "--no-xlib",
            "--avcodec-hw=none",
            "--no-videotoolbox",
            "--verbose=0",
        ]
        _log("Engine", f"Initialisation VLC monophonique (args: {vlc_args})")
        self.vlc_instance = vlc.Instance(*vlc_args)
        
        # Initialisation du slot unique
        self.slots = [VoiceSlot(self.vlc_instance, parent_widget, i) for i in range(MAX_VOICES)]
        
        # Ordre des slots actifs (au plus 1 voix en monophonie)
        self.active_voice_order = []
        
        # Pool de frames figées (mosaïque d'arrière-plan / ghosting)
        self.frozen_frames = [FrozenFrame(parent_widget, i) for i in range(MAX_FROZEN_FRAMES)]
        self.current_frozen_idx = 0
        
        # Dossier temporaire pour snapshots
        self._snap_dir = tempfile.mkdtemp(prefix="tyg_snap_")
        self._snap_counter = 0
        
        # Timer de rafraîchissement d'affichage
        self._live_timer = QTimer()
        self._live_timer.timeout.connect(self._refresh_active_videos)
        self._live_timer.start(LIVE_REFRESH_MS)
        
        _log("Engine", f"✅ Moteur monophonique initialisé (1 voix max) + {MAX_FROZEN_FRAMES} frozen frames")
        _log("Engine", f"   Rafraîchissement: {LIVE_REFRESH_MS}ms")

    def _update_audio_volumes(self):
        """En mode monophonique, volume à 100% pour la voix active."""
        for s in self.slots:
            if s.is_active and s.media_type in ("video", "audio"):
                s.set_volume(100)

    def trigger_note(self, note, filepath, in_point=0.0, out_point=0.0, video_width=0, video_height=0, velocity=None):
        """Déclenche la lecture d'un média pour une note MIDI enfoncée (monophonique : coupe toute note précédente)."""
        _log("Engine", "=" * 60)
        _log("Engine", f"Trigger Note On {note} (Monophonique) -> {os.path.basename(filepath)}")
        
        # Coupe immédiatement la note active précédente pour ne garder que la dernière note
        for s in self.slots:
            if s.is_active:
                s.stop()
        self.active_voice_order.clear()
            
        slot = self.slots[0]
        slot.note = note
        
        # Calcul de la géométrie aléatoire avec prise en compte de la vélocité et du ratio
        parent_rect = self.parent_widget.rect()
        pw, ph = parent_rect.width(), parent_rect.height()
        
        if velocity is not None:
            scale = 0.1 + (velocity / 127.0) * 1.5
        else:
            scale = random.uniform(0.3, 0.7)
            
        w = int(pw * scale)
        if video_width > 0 and video_height > 0:
            aspect = video_width / video_height
            h = int(w / aspect)
        else:
            aspect = 16 / 9
            h = int(w / aspect)
            
        if h > ph:
            h = ph
            w = int(h * aspect)
            
        x = random.randint(0, max(0, pw - w))
        y = random.randint(0, max(0, ph - h))
        geometry = QRect(x, y, w, h)
        
        # Lancement selon le type
        if _is_image(filepath):
            slot.play_image(filepath, geometry)
        elif _is_audio(filepath):
            slot.play_audio(filepath, in_point, out_point)
        else:
            slot.play_video(filepath, in_point, out_point, geometry)
            
        self.active_voice_order.append(slot)
        self._update_audio_volumes()

    def release_note(self, note):
        """Arrête le clip associé à la note relâchée uniquement si c'est la note active courante."""
        slot = self.slots[0]
        if slot.is_active and slot.note == note:
            _log("Engine", f"Note Off {note} -> arrêt slot-{slot.slot_id}")
            slot.stop()
            self.active_voice_order.clear()
            self._update_audio_volumes()

    def _refresh_active_videos(self):
        """Timer : rafraîchit les snapshots de tous les slots vidéo actifs."""
        for slot in self.slots:
            if not slot.is_active or slot.media_type != "video":
                continue
                
            # Vérifier l'atteinte du OUT-point
            if slot.out_point > slot.in_point:
                curr_ms = slot.player.get_time()
                if curr_ms > 0 and curr_ms >= int(slot.out_point * 1000):
                    if not slot.is_paused_on_out:
                        # Capture finale sur l'out-point puis pause
                        self._snap_counter += 1
                        pixmap = slot.take_snapshot(self._snap_dir, self._snap_counter)
                        if pixmap:
                            slot.live_label.setPixmap(pixmap)
                        slot.pause_on_out()
                    continue
                    
            # Si le lecteur est arrivé à la fin physique du média
            if slot.player.get_state() == vlc.State.Ended:
                if not slot.is_paused_on_out:
                    slot.pause_on_out()
                continue
                
            if slot.is_paused_on_out:
                continue
                
            # Snapshot périodique
            self._snap_counter += 1
            pixmap = slot.take_snapshot(self._snap_dir, self._snap_counter)
            if pixmap is not None:
                slot.live_label.setPixmap(pixmap)
                
                # Ajustement de l'aspect ratio dès la première frame valide reçue
                if not slot.video_aspect_adjusted:
                    vw = slot.player.video_get_width()
                    vh = slot.player.video_get_height()
                    if vw > 0 and vh > 0:
                        slot.video_aspect_adjusted = True
                        aspect = vw / vh
                        rect = slot.live_label.geometry()
                        cx = rect.x() + rect.width() / 2
                        cy = rect.y() + rect.height() / 2
                        new_w = rect.width()
                        new_h = int(new_w / aspect)
                        slot.live_label.setGeometry(QRect(int(cx - new_w / 2), int(cy - new_h / 2), new_w, new_h))

    # --- Gestion CC MIDI & Ghosting ---
    
    def get_last_active_layer(self):
        """Retourne la voix active la plus récente parmi celles encore maintenues."""
        if self.active_voice_order:
            return self.active_voice_order[-1]
        return None

    def leave_ghost(self):
        """Laisse une copie figée du clip actif le plus récent dans la mosaïque."""
        layer = self.get_last_active_layer()
        if not layer or not layer.widget.isVisible():
            return
            
        pixmap = layer.widget.pixmap()
        if pixmap is None or pixmap.isNull():
            return
            
        geometry = layer.widget.geometry()
        frozen = self.frozen_frames[self.current_frozen_idx]
        frozen.show_pixmap(pixmap, geometry)
        _log("Engine", f"  ❄ Trace rémanente (ghost) -> FrozenFrame-{self.current_frozen_idx}")
        self.current_frozen_idx = (self.current_frozen_idx + 1) % len(self.frozen_frames)

    # Rétro-compatibilité pour éventuel appel unitaire play_media
    def play_media(self, filepath, in_point=0.0, video_width=0, video_height=0, velocity=None):
        self.trigger_note(0, filepath, in_point=in_point, out_point=0.0, video_width=video_width, video_height=video_height, velocity=velocity)

    def cleanup(self):
        """Arrêt propre et libération des ressources."""
        _log("Engine", "Nettoyage complet de l'Engine")
        if self._live_timer.isActive():
            self._live_timer.stop()
        for slot in self.slots:
            slot.cleanup()
        self.slots.clear()
        self.active_voice_order.clear()
        if hasattr(self, 'vlc_instance') and self.vlc_instance:
            self.vlc_instance.release()
            self.vlc_instance = None
