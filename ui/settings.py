from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox, QHBoxLayout
import mido
from core.config import load_config, save_config
from core.midi_handler import MidiListener

class SettingsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Paramètres")
        self.resize(400, 300)
        
        self.config = load_config()
        self.midi_thread = None
        self.learning_cc = None
        
        layout = QVBoxLayout()
        
        # MIDI Device
        layout.addWidget(QLabel("Entrée MIDI :"))
        self.midi_combo = QComboBox()
        self.populate_midi_ports()
        layout.addWidget(self.midi_combo)
        
        # Learn CC section
        layout.addWidget(QLabel("Configuration des potentiomètres (Apprendre CC) :"))
        
        self.lbl_cc_scale = QLabel(f"CC Scale: {self.config.get('cc_scale', 'Non défini')}")
        btn_scale = QPushButton("Learn Scale")
        btn_scale.clicked.connect(lambda: self.start_learn("cc_scale"))
        
        self.lbl_cc_x = QLabel(f"CC Pos X: {self.config.get('cc_pos_x', 'Non défini')}")
        btn_x = QPushButton("Learn Pos X")
        btn_x.clicked.connect(lambda: self.start_learn("cc_pos_x"))
        
        self.lbl_cc_y = QLabel(f"CC Pos Y: {self.config.get('cc_pos_y', 'Non défini')}")
        btn_y = QPushButton("Learn Pos Y")
        btn_y.clicked.connect(lambda: self.start_learn("cc_pos_y"))
        
        for lbl, btn in [(self.lbl_cc_scale, btn_scale), (self.lbl_cc_x, btn_x), (self.lbl_cc_y, btn_y)]:
            h = QHBoxLayout()
            h.addWidget(lbl)
            h.addWidget(btn)
            layout.addLayout(h)
            
        save_btn = QPushButton("Sauvegarder et Fermer")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        
        self.setLayout(layout)

    def populate_midi_ports(self):
        inputs = mido.get_input_names()
        self.midi_combo.addItems(inputs)
        
        current_midi = self.config.get("midi_input", "")
        if current_midi in inputs:
            self.midi_combo.setCurrentText(current_midi)

    def start_learn(self, param_name):
        port = self.midi_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Erreur", "Sélectionnez une entrée MIDI d'abord.")
            return
            
        self.learning_cc = param_name
        self.learned_cc_values = {}  # Store initial values to detect actual movement
        
        if self.midi_thread:
            self.midi_thread.stop()
            
        self.midi_thread = MidiListener(port)
        self.midi_thread.cc_signal.connect(self.on_cc_learned)
        self.midi_thread.start()
        
        self.learn_msgbox = QMessageBox(self)
        self.learn_msgbox.setWindowTitle("Apprentissage")
        self.learn_msgbox.setText("Tournez le potentiomètre sur votre clavier MIDI...")
        self.learn_msgbox.setStandardButtons(QMessageBox.Cancel)
        self.learn_msgbox.buttonClicked.connect(self.cancel_learn)
        self.learn_msgbox.show()
        
    def cancel_learn(self):
        self.learning_cc = None
        if self.midi_thread:
            self.midi_thread.stop()
            self.midi_thread = None
            
    def on_cc_learned(self, control, value):
        if not self.learning_cc:
            return
            
        # Ignore CC if its value hasn't changed significantly (filters out static noise)
        if control not in self.learned_cc_values:
            self.learned_cc_values[control] = value
            return
            
        if abs(self.learned_cc_values[control] - value) < 3:
            return
            
        self.config[self.learning_cc] = control
        if self.learning_cc == "cc_scale":
            self.lbl_cc_scale.setText(f"CC Scale: {control}")
        elif self.learning_cc == "cc_pos_x":
            self.lbl_cc_x.setText(f"CC Pos X: {control}")
        elif self.learning_cc == "cc_pos_y":
            self.lbl_cc_y.setText(f"CC Pos Y: {control}")
        
        self.learning_cc = None
        if self.midi_thread:
            self.midi_thread.stop()
            self.midi_thread = None
            
        if hasattr(self, 'learn_msgbox') and self.learn_msgbox:
            self.learn_msgbox.accept()

    def save_settings(self):
        self.config["midi_input"] = self.midi_combo.currentText()
        save_config(self.config)
        QMessageBox.information(self, "Sauvegardé", "Paramètres sauvegardés avec succès.")
        self.close()
        
    def closeEvent(self, event):
        if self.midi_thread:
            self.midi_thread.stop()
        super().closeEvent(event)
