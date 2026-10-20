from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QEvent, QRectF
from PyQt5.QtGui import QPainter, QFont, QColor, QFontMetrics, QPainterPath


class YearHUDOverlay(QWidget):
    """
    Overlay plein écran pour afficher le dossier / l'année sélectionnée en grand
    au centre du canevas vidéo.
    Comporte une typographie cinématographique grand format avec badge sombre translucide,
    une animation 'scale punch' à chaque cran et un fondu progressif ('fade-out').
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        if parent:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())

        self._text = ""
        self._scale = 1.0
        self._opacity = 0.0

        # Animation de mise à l'échelle (scale punch à chaque changement)
        self.scale_anim = QPropertyAnimation(self, b"scale_factor")

        # Animation de fondu (disparition progressive)
        self.fade_anim = QPropertyAnimation(self, b"opacity")
        self.fade_anim.finished.connect(self._on_fade_finished)

        # Délai de maintien après relâchement (1.2 seconde)
        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.timeout.connect(self._start_fade_out)

        self.hide()

    def eventFilter(self, obj, event):
        """Ajuste automatiquement la taille dès que le canevas parent change de dimensions."""
        if obj == self.parent() and event.type() == QEvent.Resize:
            if self.parent():
                self.setGeometry(self.parent().rect())
                self.raise_()
        return super().eventFilter(obj, event)

    @pyqtProperty(float)
    def scale_factor(self):
        return self._scale

    @scale_factor.setter
    def scale_factor(self, s):
        self._scale = s
        self.update()

    @pyqtProperty(float)
    def opacity(self):
        return self._opacity

    @opacity.setter
    def opacity(self, o):
        self._opacity = max(0.0, min(1.0, o))
        self.update()

    def display_year(self, text):
        """Affiche ou met à jour le nom du dossier en grand avec un effet de punch dynamique."""
        self._text = str(text)
        self.fade_timer.stop()
        self.fade_anim.stop()
        self._opacity = 1.0

        if self.parent():
            self.setGeometry(self.parent().rect())

        self.show()
        self.raise_()

        # Animation punch: zoom dynamique (1.20 -> 1.0)
        self.scale_anim.stop()
        self.scale_anim.setDuration(160)
        self.scale_anim.setStartValue(1.20)
        self.scale_anim.setEndValue(1.0)
        self.scale_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.scale_anim.start()
        self.update()

    def cancel_fade(self):
        """Annule tout fondu en cours et maintient l'opacité maximale."""
        self.fade_timer.stop()
        self.fade_anim.stop()
        self._opacity = 1.0
        self.show()
        self.raise_()
        self.update()

    def release_pitchwheel(self):
        """Appelé lorsque la molette revient dans la zone neutre (démarre le décompte de 1.2s)."""
        self.fade_timer.stop()
        self.fade_timer.start(1200)

    def _start_fade_out(self):
        """Lance le fondu en sortie sur 450ms."""
        self.fade_anim.stop()
        self.fade_anim.setDuration(450)
        self.fade_anim.setStartValue(self._opacity)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.setEasingCurve(QEasingCurve.InQuad)
        self.fade_anim.start()

    def _on_fade_finished(self):
        """Masque le widget lorsque le fondu est complètement achevé."""
        if self._opacity <= 0.01:
            self.hide()

    def paintEvent(self, event):
        if self._opacity <= 0.001 or not self._text:
            return

        w = float(self.width())
        h = float(self.height())
        if w < 10 or h < 10:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        cx = w / 2.0
        cy = h / 2.0

        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)

        # Taille de police généreuse (environ 16% de la hauteur du canevas, min 64px, max 160px)
        font_size = max(64, min(160, int(h * 0.16)))
        font = QFont("Helvetica Neue", font_size, QFont.Bold)
        font.setStyleStrategy(QFont.PreferAntialias)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        painter.setFont(font)

        fm = QFontMetrics(font)
        text_rect = fm.boundingRect(self._text)
        text_w = text_rect.width()
        text_h = text_rect.height()

        # Badge d'arrière-plan arrondi pour une visibilité absolue sur n'importe quel fond
        pad_x = max(40, int(font_size * 0.5))
        pad_y = max(20, int(font_size * 0.25))
        badge_w = text_w + pad_x * 2
        badge_h = text_h + pad_y * 2
        badge_rect = QRectF(-badge_w / 2.0, -badge_h / 2.0, badge_w, badge_h)

        # Fond sombre translucide
        bg_alpha = int(190 * self._opacity)
        painter.setBrush(QColor(12, 12, 14, bg_alpha))
        border_alpha = int(60 * self._opacity)
        painter.setPen(QColor(255, 255, 255, border_alpha))
        painter.drawRoundedRect(badge_rect, 20.0, 20.0)

        draw_rect = QRectF(-w / 2.0, -h / 2.0, w, h)

        # Halo d'ombre sombre sous le texte
        shadow_alpha = int(220 * self._opacity)
        painter.setPen(QColor(0, 0, 0, shadow_alpha))
        for dx, dy in [(0, 3), (2, 2), (-2, 2), (0, 6)]:
            painter.drawText(draw_rect.translated(dx, dy), Qt.AlignCenter, self._text)

        # Texte principal blanc éclatant
        main_alpha = int(255 * self._opacity)
        painter.setPen(QColor(255, 255, 255, main_alpha))
        painter.drawText(draw_rect, Qt.AlignCenter, self._text)
