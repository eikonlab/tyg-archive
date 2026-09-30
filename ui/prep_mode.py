from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QListWidget, QFileDialog, QMessageBox, QLabel, 
                             QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt5.QtCore import Qt
import os
from core.library import sync_library, auto_assign_midi
from core.config import load_config, save_config

class PrepMode(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mode Préparation")
        self.resize(1000, 600)
        
        self.config = load_config()
        self.current_year = None
        
        layout = QHBoxLayout()
        
        left_panel = QVBoxLayout()
        
        self.btn_scan = QPushButton("Scanner un dossier...")
        self.btn_scan.clicked.connect(self.scan_folder)
        left_panel.addWidget(self.btn_scan)
        
        self.list_years = QListWidget()
        self.list_years.addItems(sorted(self.config.get("years", {}).keys()))
        self.list_years.itemSelectionChanged.connect(self.on_year_selected)
        left_panel.addWidget(QLabel("Années:"))
        left_panel.addWidget(self.list_years)
        
        self.btn_auto_assign = QPushButton("Auto-Assigner MIDI (Année sélectionnée)")
        self.btn_auto_assign.clicked.connect(self.auto_assign)
        left_panel.addWidget(self.btn_auto_assign)
        
        self.btn_clear = QPushButton("Vider la librairie (Reset)")
        self.btn_clear.setStyleSheet("background-color: darkred; color: white;")
        self.btn_clear.clicked.connect(self.clear_library)
        left_panel.addWidget(self.btn_clear)
        
        layout.addLayout(left_panel, 1)
        
        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("Fichiers de l'année sélectionnée :"))
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Fichier", "Type", "Note MIDI", "In", "Out"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        right_panel.addWidget(self.table)
        
        self.btn_save_table = QPushButton("Sauvegarder les modifications")
        self.btn_save_table.clicked.connect(self.save_table_changes)
        right_panel.addWidget(self.btn_save_table)
        
        layout.addLayout(right_panel, 3)
        
        self.setLayout(layout)
        
    def scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier racine")
        if folder:
            sync_library(folder)
            self.config = load_config()
            self.list_years.clear()
            self.list_years.addItems(sorted(self.config.get("years", {}).keys()))
            QMessageBox.information(self, "Scan terminé", "La librairie a été mise à jour.")
            self.table.setRowCount(0)
            self.current_year = None
            
    def clear_library(self):
        reply = QMessageBox.question(self, "Confirmation", 
                                     "Êtes-vous sûr de vouloir supprimer toutes les données et repartir à zéro ?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.config["years"] = {}
            save_config(self.config)
            self.list_years.clear()
            self.table.setRowCount(0)
            self.current_year = None
            QMessageBox.information(self, "Terminé", "La librairie a été vidée.")
            
    def auto_assign(self):
        item = self.list_years.currentItem()
        if item:
            year = item.text()
            auto_assign_midi(year)
            self.config = load_config()
            self.refresh_table(year)
            QMessageBox.information(self, "Terminé", f"Notes MIDI auto-assignées pour {year}.")

    def on_year_selected(self):
        items = self.list_years.selectedItems()
        if items:
            year = items[0].text()
            self.refresh_table(year)
            
    def refresh_table(self, year):
        self.current_year = year
        files = self.config.get("years", {}).get(year, [])
        self.table.setRowCount(len(files))
        
        for row, f in enumerate(files):
            # Filename (read only)
            filename = os.path.basename(f.get("filepath", ""))
            item_file = QTableWidgetItem(filename)
            item_file.setFlags(item_file.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, item_file)
            
            # Type (read only)
            item_type = QTableWidgetItem(f.get("type", ""))
            item_type.setFlags(item_type.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, item_type)
            
            # MIDI Note
            note = str(f.get("midi_note")) if f.get("midi_note") is not None else ""
            self.table.setItem(row, 2, QTableWidgetItem(note))
            
            # In Point
            in_p = str(f.get("in_point", 0.0))
            self.table.setItem(row, 3, QTableWidgetItem(in_p))
            
            # Out Point
            out_p = str(f.get("out_point", 0.0))
            self.table.setItem(row, 4, QTableWidgetItem(out_p))

    def save_table_changes(self):
        if not self.current_year:
            return
            
        files = self.config.get("years", {}).get(self.current_year, [])
        if len(files) != self.table.rowCount():
            QMessageBox.warning(self, "Erreur", "Le nombre de lignes ne correspond pas.")
            return
            
        for row, f in enumerate(files):
            try:
                note_str = self.table.item(row, 2).text().strip()
                f["midi_note"] = int(note_str) if note_str else None
                
                f["in_point"] = float(self.table.item(row, 3).text())
                f["out_point"] = float(self.table.item(row, 4).text())
            except ValueError:
                QMessageBox.warning(self, "Erreur", f"Format invalide à la ligne {row + 1}. Utilisez des nombres.")
                return
                
        save_config(self.config)
        QMessageBox.information(self, "Sauvegardé", f"Les modifications pour {self.current_year} ont été sauvegardées.")
