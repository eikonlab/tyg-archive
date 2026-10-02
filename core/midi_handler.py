import mido
from PyQt5.QtCore import QThread, pyqtSignal

class MidiListener(QThread):
    note_on_signal = pyqtSignal(int, int) # note, velocity
    cc_signal = pyqtSignal(int, int, int) # channel, control, value
    log_signal = pyqtSignal(str) # log messages
    
    def __init__(self, port_name):
        super().__init__()
        self.port_name = port_name
        self.running = True
        
    def run(self):
        try:
            available_ports = mido.get_input_names()
            self.log_signal.emit(f"Ports MIDI disponibles: {available_ports}")
            self.log_signal.emit(f"Tentative de connexion au port: {self.port_name}")
            
            with mido.open_input(self.port_name) as port:
                self.log_signal.emit(f"Connecté avec succès au port MIDI: {self.port_name}")
                while self.running:
                    msg = port.receive()
                    if msg.type == 'note_on' and msg.velocity > 0:
                        self.log_signal.emit(f"MIDI In -> Note On: {msg.note}, Vel: {msg.velocity}")
                        self.note_on_signal.emit(msg.note, msg.velocity)
                    elif msg.type == 'control_change':
                        self.log_signal.emit(f"MIDI In -> CC: {msg.control} (Ch {msg.channel}), Val: {msg.value}")
                        self.cc_signal.emit(msg.channel, msg.control, msg.value)
        except Exception as e:
            self.log_signal.emit(f"Erreur MIDI: {e}")
            print(f"Erreur MIDI: {e}")
            
    def stop(self):
        self.running = False
        self.quit()
        self.wait()
