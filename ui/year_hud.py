from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtGui import QPainter, QFont, QFontMetrics, QColor


class YearHUDOverlay(QWidget):
    """
    Overlay plein écran pour afficher le dossier / l'année sélectionnée au centre de l'écran.
    Comporte une typographie cinématographique avec halo subtil, une animation 'scale punch'
    à chaque passage de cran et un fondu propre ('fade-out') après relâchement.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # N'intercepte pas les clics souris
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._text = ""
        self._scale = 1.0
        self._opacity = 0.0

        # Animation de mise à l'échelle (léger rebond / punch à chaque changement)
        self.scale_anim = QPropertyAnimation(self, b"scale_factor")

        # Animation de fondu (disparition progressive)
        self.fade_anim = QPropertyAnimation(self, b"opacity")

        # Délai de maintien après relâchement avant de lancer le fondu
        self.fade_timer = QTimer(self)
        self.fade_timer.setSingleShot(True)
        self.fade_timer.timeout.connect(self._start_fade_out)

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
        """Affiche ou met à jour le texte de l'année avec un effet de punch dynamique."""
        self._text = str(text)
        self.fade_timer.stop()
        self.fade_anim.stop()
        self._opacity = 1.0

        # Animation punch: zoom léger (1.22 -> 1.0)
        self.scale_anim.stop()
        self.scale_anim.setDuration(180)
        self.scale_anim.setStartValue(1.22)
        self.scale_anim.setEndValue(1.0)
        self.scale_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.scale_anim.start()
        self.update()

    def cancel_fade(self):
        """Annule tout fondu en cours et rétablit l'opacité maximale."""
        self.fade_timer.stop()
        self.fade_anim.stop()
        self._opacity = 1.0
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

    def paintEvent(self, event):
        if self._opacity <= 0.001 or not self._text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # Taille de police généreuse et proportionnelle à la hauteur de l'écran
        font_size = max(56, int(self.height() * 0.12))
        font = QFont("-apple-system, BlinkMacSystemFont, Helvetica Neue, Arial, sans-serif", font_size, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        painter.setFont(font)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0

        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)

        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(self._text) if hasattr(metrics, 'horizontalAdvance') else metrics.width(self._text)
        text_h = metrics.height()
        tx = -text_w / 2.0
        ty = metrics.ascent() - text_h / 2.0

        # Halo / ombre cinématique douce multi-passes
        shadow_alpha = int(140 * self._opacity)
        painter.setPen(QColor(0, 0, 0, shadow_alpha))
        for dx, dy in [(0, 4), (0, -2), (2, 2), (-2, 2), (0, 7), (0, 10)]:
            painter.drawText(int(tx + dx), int(ty + dy), self._text)

        # Texte principal blanc éclatant
        main_alpha = int(255 * self._opacity)
        painter.setPen(QColor(255, 255, 255, main_alpha))
        painter.drawText(int(tx), int(ty), self._text)
