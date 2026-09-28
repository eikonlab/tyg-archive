import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from ui.settings import SettingsWindow
from ui.prep_mode import PrepMode
from ui.install_mode import InstallMode

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TYG Archives - Launcher")
        self.resize(300, 200)

        layout = QVBoxLayout()
        
        btn_prep = QPushButton("Mode Préparation (Library & In/Out)")
        btn_prep.clicked.connect(self.open_prep)
        
        btn_install = QPushButton("Mode Installation (Playback)")
        btn_install.clicked.connect(self.open_install)
        
        btn_settings = QPushButton("Paramètres (MIDI / Audio)")
        btn_settings.clicked.connect(self.open_settings)
        
        layout.addWidget(btn_prep)
        layout.addWidget(btn_install)
        layout.addWidget(btn_settings)
        
        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def open_prep(self):
        print("Ouverture du mode préparation...")
        self.prep_window = PrepMode()
        self.prep_window.show()

    def open_install(self):
        print("Ouverture du mode installation...")
        self.install_window = InstallMode()
        self.install_window.show()

    def open_settings(self):
        self.settings_window = SettingsWindow()
        self.settings_window.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
