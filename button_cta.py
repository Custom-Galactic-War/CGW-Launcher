import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtMultimedia import QSoundEffect
from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics
import constants

class CTAButtonCanvas(QWidget):
    def __init__(self, prefs):
        super().__init__()
        self.prefs = prefs
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        base_font_size = self.prefs.get('font_size', 16)
        self.font = QFont(self.prefs.get('font_family', "Consolas"), base_font_size, QFont.Weight.Medium)
        self.font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)

    def update_size(self):
        w = self.prefs.get('width', 120)
        h = self.prefs.get('height', 35)
        self.setMinimumSize(w + 40, h + 40) 
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.prefs.get('width', 120)
        h = self.prefs.get('height', 35)
        cx, cy = 20, 20
        
        is_active = self.prefs.get('is_active', False)
        base_color = QColor(self.prefs.get('color', constants.COLOR_PRIMARY))

        if is_active:
            glow = QColor(base_color)
            for i in range(8, 0, -1):
                glow.setAlpha(int(100 / (i * 1.5)))
                painter.setPen(QPen(glow, i * 2))
                painter.drawRect(cx, cy, w, h)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(base_color)
            painter.drawRect(cx, cy, w, h)
            text_color = QColor("#000000")
        else:

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(constants.COLOR_BG_DARK))
            painter.drawRect(cx, cy, w, h)

            painter.setClipRect(cx, cy, w, h)
            stripe = QColor(base_color)
            stripe.setAlpha(40) # Transparency of the stripes
            painter.setPen(QPen(stripe, 2))
            
            for i in range(-w, w * 2, 6):
                painter.drawLine(cx + i, cy - h, cx + i + w, cy + h * 2)
                
            painter.setClipping(False)
            painter.setPen(QPen(base_color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cx, cy, w, h)
            text_color = base_color

        painter.setFont(self.font)
        painter.setPen(text_color)
        
        label = self.prefs.get('label', 'SAVE')
        fm = QFontMetrics(self.font)
        text_w = fm.horizontalAdvance(label)
        text_y = cy + (h / 2) + (fm.ascent() / 2) - 2
        
        painter.drawText(int(cx + (w / 2) - (text_w / 2)), int(text_y), label)

class InteractiveCTA(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label="SAVE", width=120, height=35, click_sound_path=None, font_size=16):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.hover_sound = QSoundEffect(self)
        if os.path.exists(constants.SFX_HOVER):
            self.hover_sound.setSource(QUrl.fromLocalFile(constants.SFX_HOVER))
            self.hover_sound.setVolume(0.25)

        self.click_sound = QSoundEffect(self)
        if click_sound_path and os.path.exists(click_sound_path):
            self.click_sound.setSource(QUrl.fromLocalFile(click_sound_path))
            self.click_sound.setVolume(0.4)

        self.prefs = {
            "width": width, "height": height, "label": label,
            "color": constants.COLOR_PRIMARY, 
            "font_family": constants.load_sinclair_font(), 
            "font_size": font_size, "is_active": False
        }
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.canvas = CTAButtonCanvas(self.prefs)
        self.layout.addWidget(self.canvas)
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.canvas.update_size()

    def set_label(self, label):
        """Update the button's text and trigger a repaint. The canvas reads
        `prefs['label']` on every paintEvent, so this propagates immediately."""
        self.prefs['label'] = label
        self.canvas.update()

    def enterEvent(self, event):
        self.prefs['is_active'] = True
        self.hover_sound.play()
        self.canvas.update()
        
    def leaveEvent(self, event): 
        self.prefs['is_active'] = False
        self.canvas.update()
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: 
            self.click_sound.play()
            self.clicked.emit()