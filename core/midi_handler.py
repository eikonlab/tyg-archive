import os
import subprocess
import time
import mido
from PyQt5.QtCore import QThread, pyqtSignal

def restart_coremidi():
    """Tente de réinitialiser le serveur CoreMIDI de macOS en cas de crash/blocage (-304)."""
    try:
        if os.name == 'posix':
            uid = os.getuid()
            subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.apple.midiserver"], capture_output=True, timeout=3)
            time.sleep(0.5)
            print("[MIDI] Serveur CoreMIDI redémarré avec succès via launchctl.")
            return True
    except Exception as e:
        print(f"[MIDI] Impossible de redémarrer midiserver: {e}")
    return False

def resolve_midi_port(target_name):
    """Résout le nom de port exact, avec recherche tolérante et réveil CoreMIDI si nécessaire."""
    for attempt in range(2):
        try:
            available = mido.get_input_names()
            if not available:
                if attempt == 0 and os.name == 'posix':
                    restart_coremidi()
                    continue
                return None, available
                
            # 1. Correspondance exacte
            if target_name in available:
                return target_name, available
                
            # 2. Correspondance partielle (insensible à la casse)
            target_clean = (target_name or "").strip().lower()
            if target_clean:
                for p in available:
                    if target_clean in p.lower() or p.lower() in target_clean:
                        return p, available
                        
            # 3. S'il n'y a qu'un seul port MIDI physique/connecté
            if len(available) == 1 and target_name:
                return available[0], available
                
            return None, available
        except Exception as e:
            err_str = str(e)
            if "-304" in err_str or "OS-X MIDI client" in err_str:
                print("[MIDI] Erreur CoreMIDI -304 détectée, réinitialisation...")
                restart_coremidi()
            else:
                break
    return None, []

class MidiListener(QThread):
    note_on_signal = pyqtSignal(int, int) # note, velocity
    note_off_signal = pyqtSignal(int)     # note
    cc_signal = pyqtSignal(int, int, int) # channel, control, value
    pitchwheel_signal = pyqtSignal(int, int) # channel, pitch (-8192 to 8191)
    log_signal = pyqtSignal(str) # log messages
    
    def __init__(self, port_name):
        super().__init__()
        self.port_name = port_name
        self.running = True
        self._port = None
        
    def run(self):
        try:
            resolved_port, available_ports = resolve_midi_port(self.port_name)
            self.log_signal.emit(f"Ports MIDI disponibles: {available_ports}")
            
            if not resolved_port:
                msg = f"⚠ Port '{self.port_name}' introuvable dans {available_ports}"
                self.log_signal.emit(msg)
                print(f"[MIDI] {msg}")
                return
                
            self.log_signal.emit(f"Tentative de connexion au port: {resolved_port}")
            
            try:
                self._port = mido.open_input(resolved_port)
            except Exception as e:
                if "-304" in str(e) or "OS-X MIDI client" in str(e):
                    restart_coremidi()
                    self._port = mido.open_input(resolved_port)
                else:
                    raise e
                    
            self.log_signal.emit(f"Connecté avec succès au port MIDI: {resolved_port}")
            
            while self.running and self._port and not getattr(self._port, 'closed', False):
                msg = self._port.poll()
                if msg:
                    if msg.type == 'note_on' and msg.velocity > 0:
                        self.log_signal.emit(f"MIDI In -> Note On: {msg.note}, Vel: {msg.velocity}")
                        self.note_on_signal.emit(msg.note, msg.velocity)
                    elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                        self.log_signal.emit(f"MIDI In -> Note Off: {msg.note}")
                        self.note_off_signal.emit(msg.note)
                    elif msg.type == 'control_change':
                        self.log_signal.emit(f"MIDI In -> CC: {msg.control} (Ch {msg.channel}), Val: {msg.value}")
                        self.cc_signal.emit(msg.channel, msg.control, msg.value)
                    elif msg.type == 'pitchwheel':
                        ch = getattr(msg, 'channel', 0)
                        self.log_signal.emit(f"MIDI In -> Pitch: {msg.pitch} (Ch {ch})")
                        self.pitchwheel_signal.emit(ch, msg.pitch)
                else:
                    self.msleep(10)
        except Exception as e:
            self.log_signal.emit(f"Erreur MIDI: {e}")
            print(f"[MIDI] Erreur interceptée: {e}")
        finally:
            if self._port:
                try:
                    if not getattr(self._port, 'closed', False):
                        self._port.close()
                except Exception:
                    pass
                self._port = None

    def stop(self):
        """Arrêt propre et non bloquant du thread MIDI."""
        self.running = False
        self.quit()
        # Attendre que la boucle de run() se termine et ferme le port elle-même
        if not self.wait(500):
            # Si le thread tarde à s'arrêter (ex: CoreMIDI suspendu)
            if self._port:
                try:
                    if not getattr(self._port, 'closed', False):
                        self._port.close()
                except Exception:
                    pass
                self._port = None
            self.terminate()
            self.wait(200)
