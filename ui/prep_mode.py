import sys
import os
import time
import vlc
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QSlider, QDoubleSpinBox, QSplitter, QFrame, QAbstractItemView,
    QStackedWidget, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QMimeData, QPoint
from PyQt5.QtGui import QPixmap, QDrag, QPainter, QColor, QPen, QBrush, QFont, QKeySequence
from PyQt5.QtWidgets import QShortcut

from core.library import (
    sync_library, get_media_pool, auto_assign_fill, auto_assign_sequential,
    midi_note_to_name, _get_video_info, generate_slice_points
)
from core.config import load_config, save_config
from core.midi_handler import MidiListener

MIN_MIDI_NOTE = 28   # E0 (Clavier 76 touches)
MAX_MIDI_NOTE = 103  # G6 (Total: 76 touches)


class CueSlider(QSlider):
    """QSlider personnalisé qui surligne graphiquement la plage [IN -> OUT] sur la timeline."""
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.in_ratio = 0.0
        self.out_ratio = 1.0

    def set_cue_range(self, in_ratio, out_ratio):
        self.in_ratio = max(0.0, min(1.0, in_ratio))
        self.out_ratio = max(0.0, min(1.0, out_ratio))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.maximum() <= self.minimum():
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Coordonnées du rail de slider
        w = self.width() - 16
        h = 6
        x_start = 8
        y_pos = (self.height() - h) // 2
        
        x_in = int(x_start + self.in_ratio * w)
        x_out = int(x_start + self.out_ratio * w)
        seg_w = max(4, x_out - x_in)
        
        # Surligner la zone du cue
        highlight_color = QColor(0, 180, 216, 120)  # Cyan translucide
        painter.setBrush(QBrush(highlight_color))
        painter.setPen(QPen(QColor(0, 220, 255, 200), 1.5))
        painter.drawRoundedRect(x_in, y_pos - 2, seg_w, h + 4, 3, 3)
        
        # Marqueurs IN et OUT verticaux
        painter.setPen(QPen(QColor(80, 250, 123), 2)) # Vert IN
        painter.drawLine(x_in, y_pos - 6, x_in, y_pos + h + 6)
        
        painter.setPen(QPen(QColor(255, 85, 85), 2)) # Rouge OUT
        painter.drawLine(x_out, y_pos - 6, x_out, y_pos + h + 6)
        painter.end()


class DraggablePoolList(QListWidget):
    """QListWidget permettant de glisser-déposer (Drag) des fichiers médias vers la table de notes."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item:
            filepath = item.data(Qt.UserRole)
            if filepath:
                mime_data = QMimeData()
                mime_data.setText(filepath)
                drag = QDrag(self)
                drag.setMimeData(mime_data)
                drag.exec_(Qt.CopyAction)


class DroppableNotesTable(QTableWidget):
    """QTableWidget recevant les dépôts (Drop) de médias depuis le Media Pool."""
    media_dropped = pyqtSignal(int, str)  # row_index, filepath

    def __init__(self, rows, cols, parent=None):
        super().__init__(rows, cols, parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        filepath = event.mimeData().text()
        pos = event.pos()
        row = self.rowAt(pos.y())
        if row >= 0 and filepath:
            self.media_dropped.emit(row, filepath)
            event.acceptProposedAction()
        else:
            event.ignore()


class PrepMode(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TYG Archives - Mode Préparation (Media Pool, Clavier & Trimmer)")
        self.resize(1380, 850)
        
        self.config = load_config()
        self.current_year = None
        self.active_media_duration = 0.0
        self.audition_target_out = None
        self.is_scrubbing = False
        
        # VLC instance & player
        self.vlc_instance = vlc.Instance("--no-xlib", "--quiet")
        self.vlc_player = self.vlc_instance.media_player_new()
        
        # Timer pour synchroniser le scrubber avec la lecture vidéo
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(40) # 25 fps
        self.playback_timer.timeout.connect(self._on_playback_tick)
        
        # Configuration MIDI
        self.midi_listener = None
        self._init_midi()

        # Construction de l'interface
        self._build_ui()
        self._apply_dark_style()

        # Raccourcis clavier (Space, I, O)
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play_pause)
        QShortcut(QKeySequence(Qt.Key_I), self, self.mark_in_current)
        QShortcut(QKeySequence(Qt.Key_O), self, self.mark_out_current)

        # Charger la première année disponible
        years = sorted(self.config.get("years", {}).keys())
        if years:
            self.list_years.setCurrentRow(0)

    # -------------------------------------------------------------------------
    # Initialisation MIDI
    # -------------------------------------------------------------------------
    def _init_midi(self):
        if self.midi_listener:
            try:
                self.midi_listener.stop()
            except Exception:
                pass
            self.midi_listener = None

        port = self.config.get("midi_input", "")
        if port:
            try:
                self.midi_listener = MidiListener(port)
                self.midi_listener.note_on_signal.connect(self._on_midi_note_on)
                self.midi_listener.note_off_signal.connect(self._on_midi_note_off)
                self.midi_listener.start()
            except Exception as e:
                print(f"[PrepMode] Impossible de démarrer le listener MIDI: {e}")

    def _on_midi_listen_toggled(self, checked):
        if checked:
            if not self.midi_listener or not self.midi_listener.isRunning():
                self._init_midi()
        else:
            if self.midi_listener:
                self.midi_listener.stop()
                self.midi_listener = None

    def _on_midi_note_on(self, note, velocity):
        if not hasattr(self, 'chk_midi_listen') or not self.chk_midi_listen.isChecked():
            return
        if MIN_MIDI_NOTE <= note <= MAX_MIDI_NOTE:
            row = note - MIN_MIDI_NOTE
            self.table_notes.selectRow(row)
            self.on_note_row_selected(row)
            # Hold to play cue
            self.play_cue_audition()

    def _on_midi_note_off(self, note):
        if not hasattr(self, 'chk_midi_listen') or not self.chk_midi_listen.isChecked():
            return
        if self.vlc_player.is_playing():
            self.vlc_player.pause()

    # -------------------------------------------------------------------------
    # Construction de l'Interface Graphique (3 Colonnes)
    # -------------------------------------------------------------------------
    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # COLONNE 1 : Années & Media Pool (~320px)
        # -------------------------------------------------------------
        col1 = QVBoxLayout()
        col1_widget = QFrame()
        col1_widget.setLayout(col1)
        col1_widget.setObjectName("panelCol1")
        col1_widget.setFixedWidth(330)

        # Bouton Scan
        self.btn_scan = QPushButton("📂 Scanner un dossier racine...")
        self.btn_scan.clicked.connect(self.scan_folder)
        col1.addWidget(self.btn_scan)

        # Sélecteur d'années
        col1.addWidget(QLabel("<b>Années :</b>"))
        self.list_years = QListWidget()
        self.list_years.setMaximumHeight(110)
        self.list_years.addItems(sorted(self.config.get("years", {}).keys()))
        self.list_years.itemSelectionChanged.connect(self.on_year_selected)
        col1.addWidget(self.list_years)

        # Media Pool Header + Recherche
        pool_header = QHBoxLayout()
        pool_header.addWidget(QLabel("<b>Media Pool</b>"))
        self.lbl_pool_count = QLabel("(0 fichiers)")
        self.lbl_pool_count.setStyleSheet("color: #888;")
        pool_header.addWidget(self.lbl_pool_count)
        pool_header.addStretch()
        col1.addLayout(pool_header)

        self.txt_pool_search = QLineEdit()
        self.txt_pool_search.setPlaceholderText("🔍 Filtrer les fichiers...")
        self.txt_pool_search.textChanged.connect(self._filter_pool)
        col1.addWidget(self.txt_pool_search)

        # Liste Draggable du Pool
        self.pool_list = DraggablePoolList()
        self.pool_list.itemClicked.connect(self.on_pool_item_clicked)
        self.pool_list.itemDoubleClicked.connect(self.on_pool_item_double_clicked)
        col1.addWidget(self.pool_list, 1)

        # Boutons d'assignation rapide
        self.btn_assign_to_selected = QPushButton("➔ Assigner à la note active")
        self.btn_assign_to_selected.clicked.connect(self.assign_selected_pool_to_active_note)
        col1.addWidget(self.btn_assign_to_selected)

        self.btn_assign_next_empty = QPushButton("⚡ Assigner à la prochaine note libre")
        self.btn_assign_next_empty.clicked.connect(self.assign_selected_pool_to_next_empty)
        col1.addWidget(self.btn_assign_next_empty)

        # Reset Library
        self.btn_clear = QPushButton("⚠️ Vider la librairie (Reset)")
        self.btn_clear.setObjectName("btnDanger")
        self.btn_clear.clicked.connect(self.clear_library)
        col1.addWidget(self.btn_clear)

        main_layout.addWidget(col1_widget)

        # -------------------------------------------------------------
        # COLONNE 2 : Clavier 76 Touches (Note 28 à 103) (~430px)
        # -------------------------------------------------------------
        col2 = QVBoxLayout()
        col2_widget = QFrame()
        col2_widget.setLayout(col2)
        col2_widget.setObjectName("panelCol2")
        col2_widget.setFixedWidth(440)

        # Auto-assign toolbar
        col2.addWidget(QLabel("<b>Carte du Clavier (76 Touches)</b>"))
        auto_layout = QHBoxLayout()
        self.btn_auto_fill = QPushButton("✨ Remplir 76 touches")
        self.btn_auto_fill.setToolTip("Boucle les médias du pool sur toutes les 76 touches avec des découpages aléatoires")
        self.btn_auto_fill.clicked.connect(self.auto_assign_fill_action)
        auto_layout.addWidget(self.btn_auto_fill)

        self.btn_auto_seq = QPushButton("1-à-1 Séquentiel")
        self.btn_auto_seq.setToolTip("Assigne chaque média du pool une fois, laissant le reste libre")
        self.btn_auto_seq.clicked.connect(self.auto_assign_seq_action)
        auto_layout.addWidget(self.btn_auto_seq)
        col2.addLayout(auto_layout)

        # Statut du clavier
        self.lbl_keyboard_status = QLabel("0 / 76 touches assignées")
        self.lbl_keyboard_status.setStyleSheet("color: #00b4d8; font-weight: bold;")
        col2.addWidget(self.lbl_keyboard_status)

        # Table des 76 touches
        num_keys = MAX_MIDI_NOTE - MIN_MIDI_NOTE + 1
        self.table_notes = DroppableNotesTable(num_keys, 6)
        self.table_notes.setHorizontalHeaderLabels(["Note", "Nom", "Média assigné", "Type", "In", "Out"])
        self.table_notes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_notes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_notes.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_notes.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_notes.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_notes.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_notes.verticalHeader().setVisible(False)
        self.table_notes.cellClicked.connect(self.on_table_cell_clicked)
        self.table_notes.media_dropped.connect(self.on_media_dropped_on_table)
        col2.addWidget(self.table_notes, 1)

        # Contrôles sous la table
        table_ctrls = QHBoxLayout()
        self.btn_clear_note = QPushButton("🗑 Effacer note")
        self.btn_clear_note.clicked.connect(self.clear_selected_note)
        table_ctrls.addWidget(self.btn_clear_note)

        self.btn_duplicate_next = QPushButton("⏩ Dupliquer sur note suivante")
        self.btn_duplicate_next.clicked.connect(self.duplicate_to_next_note)
        table_ctrls.addWidget(self.btn_duplicate_next)
        col2.addLayout(table_ctrls)

        # Écoute MIDI checkbox
        self.chk_midi_listen = QCheckBox("Écouter le clavier MIDI en direct")
        self.chk_midi_listen.setChecked(True)
        self.chk_midi_listen.toggled.connect(self._on_midi_listen_toggled)
        col2.addWidget(self.chk_midi_listen)

        main_layout.addWidget(col2_widget)

        # -------------------------------------------------------------
        # COLONNE 3 : Scrubber, Lecteur VLC & Éditeur IN/OUT (~610px)
        # -------------------------------------------------------------
        col3 = QVBoxLayout()
        col3_widget = QFrame()
        col3_widget.setLayout(col3)
        col3_widget.setObjectName("panelCol3")

        # Titre du média actif
        self.lbl_editor_title = QLabel("Sélectionnez une note ou un média pour inspecter")
        self.lbl_editor_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #fff;")
        col3.addWidget(self.lbl_editor_title)

        # Zone d'affichage vidéo / image
        self.player_stack = QStackedWidget()
        self.player_stack.setMinimumHeight(340)

        # 1. Widget vidéo VLC
        self.video_container = QWidget()
        self.video_container.setStyleSheet("background-color: #000; border-radius: 6px;")
        self.player_stack.addWidget(self.video_container)

        # 2. Widget image QLabel
        self.image_label = QLabel("Aperçu d'image")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #111; color: #666; border-radius: 6px;")
        self.player_stack.addWidget(self.image_label)

        # 3. Widget audio
        self.audio_widget = QLabel("🎵 Fichier Audio")
        self.audio_widget.setAlignment(Qt.AlignCenter)
        self.audio_widget.setStyleSheet("background-color: #111; color: #ffbe0b; font-size: 18px; border-radius: 6px;")
        self.player_stack.addWidget(self.audio_widget)

        col3.addWidget(self.player_stack, 1)

        # Connecter le container vidéo à VLC
        if sys.platform == "darwin":
            self.vlc_player.set_nsobject(int(self.video_container.winId()))
        elif sys.platform.startswith("linux"):
            self.vlc_player.set_xwindow(int(self.video_container.winId()))
        elif sys.platform == "win32":
            self.vlc_player.set_hwnd(int(self.video_container.winId()))

        # Timeline Scrubber
        timeline_box = QVBoxLayout()
        time_info_layout = QHBoxLayout()
        self.lbl_time_current = QLabel("00:00.0")
        self.lbl_time_current.setStyleSheet("font-family: monospace; font-size: 14px; color: #00d2ff;")
        self.lbl_time_total = QLabel("00:00.0")
        self.lbl_time_total.setStyleSheet("font-family: monospace; font-size: 14px; color: #888;")
        time_info_layout.addWidget(self.lbl_time_current)
        time_info_layout.addStretch()
        time_info_layout.addWidget(self.lbl_time_total)
        timeline_box.addLayout(time_info_layout)

        self.slider_scrubber = CueSlider(Qt.Horizontal)
        self.slider_scrubber.setRange(0, 1000)
        self.slider_scrubber.sliderPressed.connect(self._on_scrubber_pressed)
        self.slider_scrubber.sliderReleased.connect(self._on_scrubber_released)
        self.slider_scrubber.valueChanged.connect(self._on_scrubber_changed)
        timeline_box.addWidget(self.slider_scrubber)
        col3.addLayout(timeline_box)

        # Boutons de lecture
        play_ctrls = QHBoxLayout()
        self.btn_step_back = QPushButton("◀ -1s")
        self.btn_step_back.clicked.connect(lambda: self.step_seconds(-1.0))
        play_ctrls.addWidget(self.btn_step_back)

        self.btn_play_pause = QPushButton("▶ / ❚❚ (Espace)")
        self.btn_play_pause.setObjectName("btnPrimary")
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)
        play_ctrls.addWidget(self.btn_play_pause)

        self.btn_step_forward = QPushButton("+1s ▶")
        self.btn_step_forward.clicked.connect(lambda: self.step_seconds(1.0))
        play_ctrls.addWidget(self.btn_step_forward)

        self.btn_audition_cue = QPushButton("▶ Auditionner Cue [IN ➔ OUT]")
        self.btn_audition_cue.setObjectName("btnAccent")
        self.btn_audition_cue.clicked.connect(self.play_cue_audition)
        play_ctrls.addWidget(self.btn_audition_cue)

        col3.addLayout(play_ctrls)

        # Réglage précis IN / OUT
        cue_box = QFrame()
        cue_box.setObjectName("cueBox")
        cue_layout = QHBoxLayout(cue_box)

        # IN Section
        self.btn_mark_in = QPushButton("📌 Mark IN (I)")
        self.btn_mark_in.setStyleSheet("background-color: #2b5329; color: #a6e22e; font-weight: bold;")
        self.btn_mark_in.clicked.connect(self.mark_in_current)
        cue_layout.addWidget(self.btn_mark_in)

        cue_layout.addWidget(QLabel("IN (sec):"))
        self.spin_in = QDoubleSpinBox()
        self.spin_in.setRange(0.0, 99999.0)
        self.spin_in.setSingleStep(0.1)
        self.spin_in.setDecimals(1)
        self.spin_in.valueChanged.connect(self._on_spin_in_changed)
        cue_layout.addWidget(self.spin_in)

        cue_layout.addSpacing(20)

        # OUT Section
        self.btn_mark_out = QPushButton("📌 Mark OUT (O)")
        self.btn_mark_out.setStyleSheet("background-color: #5a2020; color: #ff5555; font-weight: bold;")
        self.btn_mark_out.clicked.connect(self.mark_out_current)
        cue_layout.addWidget(self.btn_mark_out)

        cue_layout.addWidget(QLabel("OUT (sec):"))
        self.spin_out = QDoubleSpinBox()
        self.spin_out.setRange(0.0, 99999.0)
        self.spin_out.setSingleStep(0.1)
        self.spin_out.setDecimals(1)
        self.spin_out.valueChanged.connect(self._on_spin_out_changed)
        cue_layout.addWidget(self.spin_out)

        self.btn_reset_cue = QPushButton("🔄 Reset IN/OUT")
        self.btn_reset_cue.clicked.connect(self.reset_cue_to_full)
        cue_layout.addWidget(self.btn_reset_cue)

        col3.addWidget(cue_box)

        # Bouton Enregistrer
        save_layout = QHBoxLayout()
        self.lbl_save_status = QLabel("")
        self.lbl_save_status.setStyleSheet("color: #50fa7b; font-weight: bold;")
        save_layout.addWidget(self.lbl_save_status)
        save_layout.addStretch()

        self.btn_save = QPushButton("💾 Sauvegarder la configuration")
        self.btn_save.setObjectName("btnSave")
        self.btn_save.clicked.connect(self.save_all_changes)
        save_layout.addWidget(self.btn_save)

        col3.addLayout(save_layout)
        main_layout.addWidget(col3_widget, 1)

    # -------------------------------------------------------------------------
    # Stylesheet Dark Theme
    # -------------------------------------------------------------------------
    def _apply_dark_style(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #18191c;
                color: #e2e2e8;
                font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
                font-size: 13px;
            }
            QFrame#panelCol1, QFrame#panelCol2, QFrame#panelCol3 {
                background-color: #202227;
                border: 1px solid #2e3138;
                border-radius: 8px;
                padding: 4px;
            }
            QFrame#cueBox {
                background-color: #1a1b1f;
                border: 1px solid #32353e;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background-color: #2c2e36;
                color: #f0f0f5;
                border: 1px solid #3c404b;
                border-radius: 5px;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #383b45;
                border-color: #00b4d8;
            }
            QPushButton:pressed {
                background-color: #1e2025;
            }
            QPushButton#btnPrimary {
                background-color: #0077b6;
                color: white;
                font-weight: bold;
            }
            QPushButton#btnPrimary:hover {
                background-color: #0096c7;
            }
            QPushButton#btnAccent {
                background-color: #7209b7;
                color: white;
                font-weight: bold;
            }
            QPushButton#btnAccent:hover {
                background-color: #9d4edd;
            }
            QPushButton#btnSave {
                background-color: #2b8a3e;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton#btnSave:hover {
                background-color: #2f9e44;
            }
            QPushButton#btnDanger {
                background-color: #6a1a24;
                color: #ffcccc;
                border-color: #8c2430;
            }
            QPushButton#btnDanger:hover {
                background-color: #8c2430;
            }
            QListWidget, QTableWidget {
                background-color: #141518;
                border: 1px solid #282a30;
                border-radius: 6px;
                gridline-color: #23252b;
            }
            QTableWidget::item:selected, QListWidget::item:selected {
                background-color: #005080;
                color: white;
            }
            QHeaderView::section {
                background-color: #1c1d22;
                color: #aaa;
                border: none;
                border-bottom: 1px solid #2e3138;
                padding: 5px;
                font-weight: bold;
            }
            QLineEdit, QDoubleSpinBox {
                background-color: #141518;
                border: 1px solid #32353e;
                border-radius: 4px;
                color: white;
                padding: 4px 8px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #282a30;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #0077b6;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)

    # -------------------------------------------------------------------------
    # Gestion de la sélection d'Année et Chargement des Listes
    # -------------------------------------------------------------------------
    def on_year_selected(self):
        items = self.list_years.selectedItems()
        if not items:
            return
        year = items[0].text()
        self.current_year = year
        self.refresh_year_data()

    def refresh_year_data(self):
        if not self.current_year:
            return
        self._load_pool()
        self._load_notes_table()
        self.lbl_save_status.setText("")

    def _load_pool(self):
        """Remplit le Media Pool pour l'année courante."""
        self.pool_list.clear()
        pool = get_media_pool(self.current_year, self.config)
        self.lbl_pool_count.setText(f"({len(pool)} fichiers)")
        
        # Compter l'utilisation de chaque fichier dans les assignations
        assigned_counts = {}
        for item in self.config.get("years", {}).get(self.current_year, []):
            fp = item.get("filepath", "")
            assigned_counts[fp] = assigned_counts.get(fp, 0) + 1

        for m in pool:
            fp = m["filepath"]
            filename = os.path.basename(fp)
            mtype = m.get("type", "video").upper()
            
            # Badge type
            type_tag = "[VID]" if mtype == "VIDEO" else ("[IMG]" if mtype == "IMAGE" else "[AUD]")
            
            # Badge d'usage
            count = assigned_counts.get(fp, 0)
            use_tag = f"[x{count}]" if count > 0 else "[-]"
            
            item = QListWidgetItem(f"{type_tag} {use_tag} {filename}")
            item.setData(Qt.UserRole, fp)
            item.setToolTip(f"{fp}\nType: {mtype}\nAssigné à {count} touche(s)")
            
            # Couleur subtile selon utilisation
            if count > 0:
                item.setForeground(QColor(80, 250, 123)) # Vert si utilisé
            else:
                item.setForeground(QColor(200, 200, 210))
                
            self.pool_list.addItem(item)
            
        self._filter_pool(self.txt_pool_search.text())

    def _filter_pool(self, query):
        """Filtre dynamiquement les éléments du pool."""
        query = query.strip().lower()
        for i in range(self.pool_list.count()):
            item = self.pool_list.item(i)
            match = query in item.text().lower()
            item.setHidden(not match)

    def _load_notes_table(self):
        """Remplit la table des 76 touches MIDI avec les assignations de l'année."""
        assigned_map = {}
        for item in self.config.get("years", {}).get(self.current_year, []):
            note = item.get("midi_note")
            if note is not None:
                assigned_map[note] = item

        occupied_count = 0
        num_keys = MAX_MIDI_NOTE - MIN_MIDI_NOTE + 1
        self.table_notes.setRowCount(num_keys)

        for row_idx, note in enumerate(range(MIN_MIDI_NOTE, MAX_MIDI_NOTE + 1)):
            note_name = midi_note_to_name(note)
            assignment = assigned_map.get(note)

            # Col 0: Note Number
            it_num = QTableWidgetItem(str(note))
            it_num.setTextAlignment(Qt.AlignCenter)
            it_num.setFlags(it_num.flags() & ~Qt.ItemIsEditable)

            # Col 1: Note Musical Name
            it_name = QTableWidgetItem(note_name)
            it_name.setTextAlignment(Qt.AlignCenter)
            it_name.setFlags(it_name.flags() & ~Qt.ItemIsEditable)

            if assignment:
                occupied_count += 1
                fp = assignment.get("filepath", "")
                mtype = assignment.get("type", "video")
                in_p = assignment.get("in_point", 0.0)
                out_p = assignment.get("out_point", 0.0)

                it_file = QTableWidgetItem(os.path.basename(fp))
                it_file.setData(Qt.UserRole, fp)
                it_file.setToolTip(fp)

                it_type = QTableWidgetItem(mtype)
                it_type.setTextAlignment(Qt.AlignCenter)

                it_in = QTableWidgetItem(f"{in_p:.1f}s")
                it_in.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                it_out = QTableWidgetItem(f"{out_p:.1f}s")
                it_out.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                # Style ligne assignée
                it_num.setForeground(QColor(0, 210, 255))
                it_name.setForeground(QColor(0, 210, 255))
                it_file.setForeground(QColor(240, 240, 255))
            else:
                it_file = QTableWidgetItem("--- Libre ---")
                it_file.setForeground(QColor(90, 90, 100))
                it_type = QTableWidgetItem("-")
                it_type.setTextAlignment(Qt.AlignCenter)
                it_type.setForeground(QColor(90, 90, 100))
                it_in = QTableWidgetItem("-")
                it_in.setTextAlignment(Qt.AlignCenter)
                it_in.setForeground(QColor(90, 90, 100))
                it_out = QTableWidgetItem("-")
                it_out.setTextAlignment(Qt.AlignCenter)
                it_out.setForeground(QColor(90, 90, 100))

            it_file.setFlags(it_file.flags() & ~Qt.ItemIsEditable)
            it_type.setFlags(it_type.flags() & ~Qt.ItemIsEditable)
            it_in.setFlags(it_in.flags() & ~Qt.ItemIsEditable)
            it_out.setFlags(it_out.flags() & ~Qt.ItemIsEditable)

            self.table_notes.setItem(row_idx, 0, it_num)
            self.table_notes.setItem(row_idx, 1, it_name)
            self.table_notes.setItem(row_idx, 2, it_file)
            self.table_notes.setItem(row_idx, 3, it_type)
            self.table_notes.setItem(row_idx, 4, it_in)
            self.table_notes.setItem(row_idx, 5, it_out)

        self.lbl_keyboard_status.setText(f"{occupied_count} / {num_keys} touches assignées")

    # -------------------------------------------------------------------------
    # Actions d'Assignation (Drag & Drop, Boutons, Double-Clic)
    # -------------------------------------------------------------------------
    def on_media_dropped_on_table(self, row, filepath):
        """Réception d'un média glissé-déposé sur une ligne de la table des notes."""
        note = MIN_MIDI_NOTE + row
        self._assign_media_to_note(note, filepath)
        self.table_notes.selectRow(row)
        self.on_note_row_selected(row)

    def on_pool_item_clicked(self, item):
        """Clic sur un média du pool : prévisualise le média dans le lecteur."""
        filepath = item.data(Qt.UserRole)
        if filepath:
            self._preview_media_file(filepath, title_prefix="Media Pool")

    def on_pool_item_double_clicked(self, item):
        """Double-clic sur un média du pool : l'assigne à la note sélectionnée."""
        self.assign_selected_pool_to_active_note()

    def assign_selected_pool_to_active_note(self):
        """Assigne le média sélectionné du pool à la note actuellement sélectionnée."""
        pool_item = self.pool_list.currentItem()
        if not pool_item:
            QMessageBox.information(self, "Info", "Sélectionnez un média dans le pool.")
            return
            
        selected_rows = self.table_notes.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Info", "Sélectionnez une ligne de note dans le tableau.")
            return
            
        filepath = pool_item.data(Qt.UserRole)
        row = selected_rows[0].row()
        note = MIN_MIDI_NOTE + row
        self._assign_media_to_note(note, filepath)
        self.on_note_row_selected(row)

    def assign_selected_pool_to_next_empty(self):
        """Assigne le média sélectionné à la première touche libre disponible."""
        pool_item = self.pool_list.currentItem()
        if not pool_item:
            QMessageBox.information(self, "Info", "Sélectionnez un média dans le pool.")
            return
        filepath = pool_item.data(Qt.UserRole)
        
        # Chercher la première note libre
        assigned_notes = {
            item.get("midi_note") 
            for item in self.config.get("years", {}).get(self.current_year, [])
        }
        for note in range(MIN_MIDI_NOTE, MAX_MIDI_NOTE + 1):
            if note not in assigned_notes:
                self._assign_media_to_note(note, filepath)
                row = note - MIN_MIDI_NOTE
                self.table_notes.selectRow(row)
                self.on_note_row_selected(row)
                return
                
        QMessageBox.information(self, "Complet", "Toutes les 76 touches sont déjà assignées !")

    def _assign_media_to_note(self, note, filepath):
        """Enregistre l'assignation d'un média sur une note avec génération de points IN/OUT."""
        if not self.current_year or not filepath:
            return
            
        ext = os.path.splitext(filepath)[1].lower()
        mtype = "image" if ext in {".jpg", ".jpeg", ".png"} else ("audio" if ext == ".wav" else "video")
        
        if mtype == "video":
            in_p, out_p, w, h, dur = generate_slice_points(filepath)
        else:
            in_p, out_p, w, h = 0.0, 0.0, 0, 0

        year_list = self.config.setdefault("years", {}).setdefault(self.current_year, [])
        
        # Mettre à jour si la note existe déjà, sinon ajouter
        found = False
        for item in year_list:
            if item.get("midi_note") == note:
                item["filepath"] = filepath
                item["type"] = mtype
                item["in_point"] = in_p
                item["out_point"] = out_p
                item["width"] = w
                item["height"] = h
                found = True
                break
                
        if not found:
            year_list.append({
                "midi_note": note,
                "filepath": filepath,
                "type": mtype,
                "in_point": in_p,
                "out_point": out_p,
                "width": w,
                "height": h
            })

        # Re-trier par note
        year_list.sort(key=lambda x: x.get("midi_note") if x.get("midi_note") is not None else 999)
        self._load_notes_table()
        self._load_pool() # mettre à jour les compteurs de pool

    def clear_selected_note(self):
        """Supprime l'assignation sur la note sélectionnée."""
        selected_rows = self.table_notes.selectionModel().selectedRows()
        if not selected_rows or not self.current_year:
            return
        row = selected_rows[0].row()
        note = MIN_MIDI_NOTE + row
        
        year_list = self.config.get("years", {}).get(self.current_year, [])
        self.config["years"][self.current_year] = [item for item in year_list if item.get("midi_note") != note]
        
        self._load_notes_table()
        self._load_pool()
        self.table_notes.selectRow(row)
        self.on_note_row_selected(row)

    def duplicate_to_next_note(self):
        """Duplique le clip et ses réglages vers la note suivante (idéal pour découper des sous-extraits)."""
        selected_rows = self.table_notes.selectionModel().selectedRows()
        if not selected_rows or not self.current_year:
            return
        row = selected_rows[0].row()
        note = MIN_MIDI_NOTE + row
        next_note = note + 1
        if next_note > MAX_MIDI_NOTE:
            QMessageBox.information(self, "Limite", "Vous êtes déjà sur la dernière note (103).")
            return
            
        current_item = None
        for item in self.config.get("years", {}).get(self.current_year, []):
            if item.get("midi_note") == note:
                current_item = item
                break
                
        if not current_item:
            QMessageBox.information(self, "Vide", "La note sélectionnée n'a pas de média assigné à dupliquer.")
            return
            
        # Dupliquer avec les mêmes paramètres
        year_list = self.config.setdefault("years", {}).setdefault(self.current_year, [])
        found = False
        for item in year_list:
            if item.get("midi_note") == next_note:
                item["filepath"] = current_item["filepath"]
                item["type"] = current_item["type"]
                item["in_point"] = current_item.get("in_point", 0.0)
                item["out_point"] = current_item.get("out_point", 0.0)
                item["width"] = current_item.get("width", 0)
                item["height"] = current_item.get("height", 0)
                found = True
                break
        if not found:
            year_list.append({
                "midi_note": next_note,
                "filepath": current_item["filepath"],
                "type": current_item["type"],
                "in_point": current_item.get("in_point", 0.0),
                "out_point": current_item.get("out_point", 0.0),
                "width": current_item.get("width", 0),
                "height": current_item.get("height", 0)
            })
            
        year_list.sort(key=lambda x: x.get("midi_note") if x.get("midi_note") is not None else 999)
        self._load_notes_table()
        self._load_pool()
        next_row = next_note - MIN_MIDI_NOTE
        self.table_notes.selectRow(next_row)
        self.on_note_row_selected(next_row)

    # -------------------------------------------------------------------------
    # Auto-Assign Routines
    # -------------------------------------------------------------------------
    def auto_assign_fill_action(self):
        if not self.current_year:
            return
        reply = QMessageBox.question(
            self, "Confirmer Remplissage 76 Touches",
            f"Voulez-vous remplir automatiquement toutes les 76 touches pour {self.current_year} en découpant des tranches aléatoires du pool ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            auto_assign_fill(self.current_year)
            self.config = load_config()
            self.refresh_year_data()
            QMessageBox.information(self, "Terminé", f"76 touches configurées pour {self.current_year}.")

    def auto_assign_seq_action(self):
        if not self.current_year:
            return
        auto_assign_sequential(self.current_year)
        self.config = load_config()
        self.refresh_year_data()
        QMessageBox.information(self, "Terminé", f"Assignation 1-à-1 appliquée pour {self.current_year}.")

    # -------------------------------------------------------------------------
    # Gestion du Lecteur & Scrubber (Colonne 3)
    # -------------------------------------------------------------------------
    def on_table_cell_clicked(self, row, col):
        self.on_note_row_selected(row)

    def on_note_row_selected(self, row):
        """Charge la note sélectionnée dans l'éditeur et le lecteur vidéo."""
        note = MIN_MIDI_NOTE + row
        note_name = midi_note_to_name(note)
        
        # Chercher l'assignation
        assigned = None
        for item in self.config.get("years", {}).get(self.current_year, []):
            if item.get("midi_note") == note:
                assigned = item
                break
                
        if not assigned:
            self.lbl_editor_title.setText(f"Note {note} ({note_name}) : --- Libre ---")
            self._stop_playback()
            self.player_stack.setCurrentIndex(1)
            self.image_label.setText("Aucun média assigné.\nGlissez un fichier depuis le Media Pool pour l'assigner à cette note.")
            self._reset_scrubber_controls(0.0)
            return

        fp = assigned.get("filepath", "")
        in_p = assigned.get("in_point", 0.0)
        out_p = assigned.get("out_point", 0.0)

        # Enrichir dimensions si inconnues
        if assigned.get("type") == "video" and (assigned.get("width", 0) <= 0 or assigned.get("height", 0) <= 0):
            info = _get_video_info(fp)
            assigned["width"] = info.get("width", 0)
            assigned["height"] = info.get("height", 0)

        self._load_media_in_player(fp, in_p, out_p, title_prefix=f"Note {note} ({note_name})")

    def _preview_media_file(self, filepath, title_prefix="Media Pool"):
        """Prévisualise directement un fichier depuis le pool sans modifier les assignations."""
        info = _get_video_info(filepath)
        dur = info.get("duration", 0.0)
        self._load_media_in_player(filepath, 0.0, dur, title_prefix=title_prefix)

    def _load_media_in_player(self, filepath, in_point, out_point, title_prefix=""):
        """Charge et initialise un fichier dans le lecteur multimédia."""
        self._stop_playback()
        filename = os.path.basename(filepath)
        self.lbl_editor_title.setText(f"{title_prefix} : {filename}")
        
        ext = os.path.splitext(filepath)[1].lower()
        if ext in {".jpg", ".jpeg", ".png"}:
            # Image
            self.player_stack.setCurrentIndex(1)
            pix = QPixmap(filepath)
            if not pix.isNull():
                self.image_label.setPixmap(pix.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self._reset_scrubber_controls(0.0)
        elif ext == ".wav":
            # Audio
            self.player_stack.setCurrentIndex(2)
            self._init_vlc_media(filepath, in_point, out_point)
        else:
            # Vidéo
            self.player_stack.setCurrentIndex(0)
            self._init_vlc_media(filepath, in_point, out_point)

    def _init_vlc_media(self, filepath, in_point, out_point):
        """Configure VLC pour la vidéo ou l'audio avec scrubber et cue points."""
        media = self.vlc_instance.media_new(filepath)
        self.vlc_player.set_media(media)
        
        # Récupérer durée
        info = _get_video_info(filepath)
        duration = info.get("duration", 0.0)
        if duration <= 0:
            # Fallback VLC parsing
            media.parse()
            duration = max(0.0, media.get_duration() / 1000.0)
            
        self.active_media_duration = duration
        self._setup_scrubber_controls(duration, in_point, out_point)
        
        # Positionner le lecteur sur le in_point
        self.vlc_player.play()
        # Petit délai pour laisser VLC initialiser avant pause
        QTimer.singleShot(150, lambda: self._seek_and_pause(in_point))

    def _seek_and_pause(self, target_sec):
        self.vlc_player.pause()
        self.vlc_player.set_time(int(target_sec * 1000))
        self._update_time_labels(target_sec, self.active_media_duration)
        if self.active_media_duration > 0:
            val = int((target_sec / self.active_media_duration) * 1000)
            self.slider_scrubber.blockSignals(True)
            self.slider_scrubber.setValue(val)
            self.slider_scrubber.blockSignals(False)

    def _setup_scrubber_controls(self, duration, in_point, out_point):
        """Met à jour les bornes et valeurs des contrôles du scrubber."""
        self.active_media_duration = duration
        out_val = out_point if out_point > 0 else duration

        self.spin_in.blockSignals(True)
        self.spin_out.blockSignals(True)
        self.spin_in.setMaximum(duration)
        self.spin_out.setMaximum(duration)
        self.spin_in.setValue(in_point)
        self.spin_out.setValue(out_val)
        self.spin_in.blockSignals(False)
        self.spin_out.blockSignals(False)

        # Mettre à jour le visualiseur de cue sur le slider
        in_ratio = (in_point / duration) if duration > 0 else 0.0
        out_ratio = (out_val / duration) if duration > 0 else 1.0
        self.slider_scrubber.set_cue_range(in_ratio, out_ratio)
        self._update_time_labels(in_point, duration)

    def _reset_scrubber_controls(self, duration):
        self.active_media_duration = duration
        self.spin_in.blockSignals(True)
        self.spin_out.blockSignals(True)
        self.spin_in.setValue(0.0)
        self.spin_out.setValue(0.0)
        self.spin_in.blockSignals(False)
        self.spin_out.blockSignals(False)
        self.slider_scrubber.set_cue_range(0.0, 1.0)
        self._update_time_labels(0.0, 0.0)

    def _format_time(self, seconds):
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins:02d}:{secs:04.1f}"

    def _update_time_labels(self, cur_sec, total_sec):
        self.lbl_time_current.setText(self._format_time(cur_sec))
        self.lbl_time_total.setText(self._format_time(total_sec))

    # -------------------------------------------------------------------------
    # Événements Scrubber Slider
    # -------------------------------------------------------------------------
    def _on_scrubber_pressed(self):
        self.is_scrubbing = True
        if self.vlc_player.is_playing():
            self.vlc_player.pause()

    def _on_scrubber_released(self):
        self.is_scrubbing = False

    def _on_scrubber_changed(self, value):
        if self.active_media_duration <= 0:
            return
        target_sec = (value / 1000.0) * self.active_media_duration
        self._update_time_labels(target_sec, self.active_media_duration)
        if self.is_scrubbing:
            self.vlc_player.set_time(int(target_sec * 1000))

    def _on_playback_tick(self):
        """Timer régulier mettant à jour le scrubber et gérant la fin du cue d'audition."""
        if not self.vlc_player.is_playing():
            return
        cur_ms = self.vlc_player.get_time()
        if cur_ms < 0:
            return
        cur_sec = cur_ms / 1000.0
        
        # Vérifier si on a dépassé le point OUT en mode audition
        if self.audition_target_out is not None and cur_sec >= self.audition_target_out:
            self.vlc_player.pause()
            self.audition_target_out = None
            return

        if not self.is_scrubbing and self.active_media_duration > 0:
            val = int((cur_sec / self.active_media_duration) * 1000)
            self.slider_scrubber.blockSignals(True)
            self.slider_scrubber.setValue(val)
            self.slider_scrubber.blockSignals(False)
            self._update_time_labels(cur_sec, self.active_media_duration)

    def toggle_play_pause(self):
        """Bascule Lecture / Pause."""
        if self.vlc_player.is_playing():
            self.vlc_player.pause()
            self.playback_timer.stop()
        else:
            self.audition_target_out = None
            self.vlc_player.play()
            self.playback_timer.start()

    def step_seconds(self, delta_sec):
        """Avance ou recule d'un delta en secondes."""
        cur_ms = self.vlc_player.get_time()
        new_sec = max(0.0, min(self.active_media_duration, (cur_ms / 1000.0) + delta_sec))
        self._seek_and_pause(new_sec)

    def play_cue_audition(self):
        """Joue uniquement le segment IN -> OUT pour valider le cue audio/vidéo."""
        in_p = self.spin_in.value()
        out_p = self.spin_out.value()
        if out_p <= in_p:
            out_p = self.active_media_duration

        self.audition_target_out = out_p
        self.vlc_player.set_time(int(in_p * 1000))
        self.vlc_player.play()
        self.playback_timer.start()

    def mark_in_current(self):
        """Fixe le point IN à la position actuelle du playhead."""
        cur_ms = self.vlc_player.get_time()
        cur_sec = round(max(0.0, cur_ms / 1000.0), 1)
        self.spin_in.setValue(cur_sec)
        self._on_spin_in_changed(cur_sec)

    def mark_out_current(self):
        """Fixe le point OUT à la position actuelle du playhead."""
        cur_ms = self.vlc_player.get_time()
        cur_sec = round(max(0.0, cur_ms / 1000.0), 1)
        self.spin_out.setValue(cur_sec)
        self._on_spin_out_changed(cur_sec)

    def reset_cue_to_full(self):
        """Réinitialise les points IN et OUT sur la totalité du clip."""
        self.spin_in.setValue(0.0)
        self.spin_out.setValue(self.active_media_duration)
        self._on_spin_in_changed(0.0)
        self._on_spin_out_changed(self.active_media_duration)

    def _on_spin_in_changed(self, value):
        in_val = value
        out_val = self.spin_out.value()
        if in_val > out_val and out_val > 0:
            self.spin_out.setValue(in_val)
            out_val = in_val

        if self.active_media_duration > 0:
            self.slider_scrubber.set_cue_range(in_val / self.active_media_duration, out_val / self.active_media_duration)
        self._apply_cue_to_active_note()

    def _on_spin_out_changed(self, value):
        out_val = value
        in_val = self.spin_in.value()
        if out_val < in_val:
            self.spin_in.setValue(out_val)
            in_val = out_val

        if self.active_media_duration > 0:
            self.slider_scrubber.set_cue_range(in_val / self.active_media_duration, out_val / self.active_media_duration)
        self._apply_cue_to_active_note()

    def _apply_cue_to_active_note(self):
        """Met à jour les valeurs IN et OUT dans la configuration pour la note active."""
        selected_rows = self.table_notes.selectionModel().selectedRows()
        if not selected_rows or not self.current_year:
            return
        row = selected_rows[0].row()
        note = MIN_MIDI_NOTE + row
        
        in_p = self.spin_in.value()
        out_p = self.spin_out.value()

        # Mettre à jour l'élément dans config
        for item in self.config.get("years", {}).get(self.current_year, []):
            if item.get("midi_note") == note:
                item["in_point"] = in_p
                item["out_point"] = out_p
                break

        # Mettre à jour l'affichage de la table
        item_in = self.table_notes.item(row, 4)
        item_out = self.table_notes.item(row, 5)
        if item_in:
            item_in.setText(f"{in_p:.1f}s")
        if item_out:
            item_out.setText(f"{out_p:.1f}s")

    def _stop_playback(self):
        self.playback_timer.stop()
        if self.vlc_player.is_playing():
            self.vlc_player.stop()

    # -------------------------------------------------------------------------
    # Persistance & Gestion Globale
    # -------------------------------------------------------------------------
    def scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier racine des archives")
        if folder:
            sync_library(folder)
            self.config = load_config()
            self.list_years.clear()
            self.list_years.addItems(sorted(self.config.get("years", {}).keys()))
            QMessageBox.information(self, "Scan terminé", "La librairie a été synchronisée avec succès.")
            if self.list_years.count() > 0:
                self.list_years.setCurrentRow(0)

    def clear_library(self):
        reply = QMessageBox.question(
            self, "Confirmation",
            "Êtes-vous sûr de vouloir supprimer toutes les assignations et vider la librairie ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.config["years"] = {}
            if "media_pool" in self.config:
                self.config["media_pool"] = {}
            save_config(self.config)
            self.list_years.clear()
            self.pool_list.clear()
            self.table_notes.setRowCount(0)
            self._stop_playback()
            self.current_year = None
            QMessageBox.information(self, "Terminé", "La librairie a été vidée.")

    def save_all_changes(self):
        """Sauvegarde les modifications dans config.json."""
        save_config(self.config)
        self.lbl_save_status.setText("✓ Modifications enregistrées avec succès !")
        QTimer.singleShot(4000, lambda: self.lbl_save_status.setText(""))

    def closeEvent(self, event):
        """Nettoyage des threads et instances VLC à la fermeture."""
        self._stop_playback()
        if self.midi_listener:
            self.midi_listener.stop()
            self.midi_listener = None
        self.vlc_player.release()
        event.accept()
