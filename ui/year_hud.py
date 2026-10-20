from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QEvent, QRectF
from PyQt5.QtGui import QPainter, QFont, QColor


class YearHUDOverlay(QWidget):
    """
    Overlay plein écran pour afficher le dossier / l'année sélectionnée en grand
    au centre du canevas vidéo.
    Comporte une typographie cinématographique grand format avec halo sombre haute lisibilité,
    une animation 'scale punch' à chaque cran et un fondu progressif ('fade-out').
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # N'intercepte pas les clics souris
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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

        # Délai de maintien après relâchement (1 seconde)
        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.timeout.connect(self._start_fade_out)

        self.hide()

    def eventFilter(self, obj, event):
        """Ajuste automatiquement la taille dès que le canevas parent change de dimensions."""
        if obj == self.parent() and event.type() == QEvent.Resize:
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

        # Animation punch: zoom dynamique (1.25 -> 1.0)
        self.scale_anim.stop()
        self.scale_anim.setDuration(180)
        self.scale_anim.setStartValue(1.25)
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
        """Appelé lorsque la molette revient dans la zone neutre (démarre le décompte de 1s)."""
        self.fade_timer.stop()
        self.fade_timer.start(1000)

    def _start_fade_out(self):
        """Lance le fondu en sortie sur 400ms."""
        self.fade_anim.stop()
        self.fade_anim.setDuration(400)
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

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # Taille de police généreuse (environ 18% de la hauteur du canevas, min 72px)
        font_size = max(72, int(self.height() * 0.18))
        font = QFont("-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif", font_size, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        painter.setFont(font)

        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0
        cy = h / 2.0

        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)

        draw_rect = QRectF(-w / 2.0, -h / 2.0, w, h)

        # Halo d'ombre multi-passes prononcé pour contraste parfait sur vidéo sombre ou claire
        shadow_alpha = int(200 * self._opacity)
        painter.setPen(QColor(0, 0, 0, shadow_alpha))
        for dx, dy in [(0, 4), (0, -3), (3, 3), (-3, 3), (0, 8), (0, 12), (0, -4)]:
            painter.drawText(draw_rect.translated(dx, dy), Qt.AlignCenter, self._text)

        # Texte principal blanc éclatant
        main_alpha = int(255 * self._opacity)
        painter.setPen(QColor(255, 255, 255, main_alpha))
        painter.drawText(draw_rect, Qt.AlignCenter, self._text)
