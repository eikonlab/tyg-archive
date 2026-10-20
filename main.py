import os
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from ui.settings import SettingsWindow
from ui.prep_mode import PrepMode
from ui.install_mode import InstallMode

def setup_crash_proof_hooks():
    """Intercepte les exceptions non gérées pour éviter le crash SIGABRT brutal de PyQt5."""
    def excepthook(exc_type, exc_value, exc_traceback):
        import traceback
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(f"[CRASH PREVENTED] Exception interceptée sans interruption de l'app:\n{err_msg}", file=sys.stderr)
    sys.excepthook = excepthook

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

        # Style sombre moderne et épuré
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
                font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            }
            QPushButton {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                padding: 12px 16px;
                font-size: 13px;
                font-weight: 500;
                margin: 4px 0px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
            }
        """)

        self.prep_window = None
        self.install_window = None
        self.settings_window = None

    def open_prep(self):
        print("Ouverture du mode préparation...")
        # Fermer le mode installation s'il tourne pour libérer le port MIDI
        if self.install_window and self.install_window.isVisible():
            self.install_window.close_and_stop()
            self.install_window = None
        if self.prep_window and self.prep_window.isVisible():
            self.prep_window.raise_()
            self.prep_window.activateWindow()
            return
        self.prep_window = PrepMode(parent_launcher=self)
        self.prep_window.show()

    def open_install(self):
        print("Ouverture du mode installation...")
        # Fermer le mode préparation s'il tourne pour libérer le port MIDI
        if self.prep_window and self.prep_window.isVisible():
            self.prep_window.close()
            self.prep_window = None
        if self.install_window and self.install_window.isVisible():
            self.install_window.raise_()
            self.install_window.activateWindow()
            return
        self.install_window = InstallMode(parent_launcher=self)
        self.install_window.show()

    def open_settings(self):
        if self.settings_window and self.settings_window.isVisible():
            self.settings_window.raise_()
            self.settings_window.activateWindow()
            return
        self.settings_window = SettingsWindow()
        self.settings_window.show()

    def closeEvent(self, event):
        if self.prep_window:
            try:
                self.prep_window.close()
            except Exception:
                pass
            self.prep_window = None
        if self.install_window:
            try:
                self.install_window.close_and_stop()
            except Exception:
                pass
            self.install_window = None
        if self.settings_window:
            try:
                self.settings_window.close()
            except Exception:
                pass
            self.settings_window = None
        event.accept()
        QApplication.quit()

if __name__ == "__main__":
    setup_crash_proof_hooks()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec_()
    # Arrêt immédiat et propre : empêche tout thread C (CoreMIDI / libvlc) résiduel de bloquer sous macOS
    os._exit(exit_code)
