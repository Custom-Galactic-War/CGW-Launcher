import os
import re
import html
import math
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QLabel, QGraphicsOpacityEffect, QFrame, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QPushButton,
)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QPolygonF, QPixmap, QCursor
from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, QElapsedTimer, QLineF, pyqtSignal

import constants

class LinkButtonWidget(QLabel):
    # Discord button
    def __init__(self, icon_path, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        # Opacity effect
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity_effect)

        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(35, 35, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(pixmap)

    def enterEvent(self, event):
        self.opacity_effect.setOpacity(0.6)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.opacity_effect.setOpacity(1.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            webbrowser.open(self.url)
        super().mousePressEvent(event)


# Generic clickable icon. If the icon file is missing, it falls back to
# painting a primary-colored circle with a single letter (e.g. 'i') so the
# launcher still has a working button even if the asset isn't shipped.
class IconButton(QLabel):
    clicked = pyqtSignal()

    def __init__(self, icon_path=None, fallback_letter="i", tooltip="", size=35, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._fallback_letter = fallback_letter
        self._size = size
        if tooltip:
            self.setToolTip(tooltip)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity_effect)

        self._icon_loaded = False
        if icon_path and os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(pixmap)
            self._icon_loaded = True
        else:
            self.setFixedSize(size, size)

    def enterEvent(self, event):
        self.opacity_effect.setOpacity(0.6)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.opacity_effect.setOpacity(1.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        if self._icon_loaded:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(2, 2, -2, -2)
        primary = QColor(constants.COLOR_PRIMARY)

        painter.setPen(QPen(primary, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)

        font = QFont(constants.load_sinclair_font(), int(self._size * 0.55), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(primary)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._fallback_letter)


# ---------------------------------------------------------------------------
# Instructions overlay
# ---------------------------------------------------------------------------

def _format_inline(text):
    #Inline transforms applied after HTML-escaping the line.
    escaped = html.escape(text)
    # **bold**
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    # *italic* (avoid matching ** by requiring single-asterisk boundaries)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", escaped)
    # Bare URLs become clickable links
    escaped = re.sub(
        r"(https?://[^\s<]+)",
        rf'<a href="\1" style="color:{constants.COLOR_PRIMARY};">\1</a>',
        escaped,
    )
    return escaped


def instructions_text_to_html(text):
    """Convert the lightly-formatted instructions.txt into styled HTML.

    Recognized patterns:
      ### Title ###     -> H1 heading (primary color)
      ## Heading        -> H2
      # Heading         -> H1
      Word:             -> H2 sub-heading (single line ending in colon)
      1. step           -> ordered-list item (consecutive => <ol>)
      - bullet          -> unordered-list item (consecutive => <ul>)
      blank line        -> paragraph break (does NOT break a list of the
                           same kind, so blank-line-separated steps still
                           number 1, 2, 3, ... rather than each restarting)
      everything else   -> paragraph
    Inline: **bold**, *italic*, http(s) links.
    """
    primary = constants.COLOR_PRIMARY
    text_color = constants.COLOR_TEXT_LIGHT

    parts = []
    list_mode = None  # None | "ul" | "ol"
    pending_blanks = 0

    def close_list():
        nonlocal list_mode
        if list_mode:
            parts.append(f"</{list_mode}>")
            list_mode = None

    def flush_blanks():
        nonlocal pending_blanks
        for _ in range(pending_blanks):
            parts.append("<div style='height:6px;'></div>")
        pending_blanks = 0

    def open_list(kind):
        nonlocal list_mode
        if list_mode != kind:
            close_list()
            flush_blanks()
            style = "margin:6px 0 10px 4px; padding-left:22px; line-height:1.55;"
            parts.append(f"<{kind} style='{style}'>")
            list_mode = kind
        else:
            # Same list continuing — drop blank lines so numbering keeps going.
            pending_blanks = 0

    for raw in text.splitlines():
        stripped = raw.strip()

        if not stripped:
            pending_blanks += 1
            continue

        # ### TITLE ### style — strip leading/trailing hashes.
        m = re.fullmatch(r"#{2,}\s*(.+?)\s*#{2,}", stripped)
        if m:
            close_list()
            flush_blanks()
            parts.append(
                f"<h1 style='color:{primary}; font-size:20px; "
                f"margin:14px 0 10px; letter-spacing:1px;'>{html.escape(m.group(1))}</h1>"
            )
            continue

        if stripped.startswith("### "):
            close_list()
            flush_blanks()
            parts.append(
                f"<h3 style='color:{primary}; font-size:15px; margin:12px 0 4px;'>"
                f"{html.escape(stripped[4:])}</h3>"
            )
            continue
        if stripped.startswith("## "):
            close_list()
            flush_blanks()
            parts.append(
                f"<h2 style='color:{primary}; font-size:17px; margin:14px 0 6px;'>"
                f"{html.escape(stripped[3:])}</h2>"
            )
            continue
        if stripped.startswith("# "):
            close_list()
            flush_blanks()
            parts.append(
                f"<h1 style='color:{primary}; font-size:20px; margin:16px 0 8px;'>"
                f"{html.escape(stripped[2:])}</h1>"
            )
            continue

        # Bullet list
        m = re.match(r"^[-*]\s+(.*)", stripped)
        if m:
            open_list("ul")
            parts.append(f"<li style='margin-bottom:8px;'>{_format_inline(m.group(1))}</li>")
            continue

        # Numbered list
        m = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if m:
            open_list("ol")
            parts.append(f"<li style='margin-bottom:8px;'>{_format_inline(m.group(2))}</li>")
            continue

        # Standalone "Notes:" style sub-heading
        if re.fullmatch(r"[A-Za-z0-9 ]{1,40}:", stripped):
            close_list()
            flush_blanks()
            parts.append(
                f"<h2 style='color:{primary}; font-size:16px; margin:16px 0 6px;'>"
                f"{html.escape(stripped)}</h2>"
            )
            continue

        # Regular paragraph
        close_list()
        flush_blanks()
        parts.append(
            f"<p style='margin:6px 0; line-height:1.55;'>{_format_inline(stripped)}</p>"
        )

    close_list()

    body = "\n".join(parts)
    return f"""
    <html><body style='color:{text_color}; font-family:Consolas, monospace; font-size:13px;'>
    {body}
    </body></html>
    """


class InstructionsOverlay(QWidget):
    """Full-launcher overlay that displays Instructions.txt in a styled panel.

    Click the dimmed backdrop, the X button, the GOT IT button, or press Esc
    to dismiss.
    """

    closed = pyqtSignal()

    def __init__(self, instructions_text, parent=None):
        super().__init__(parent)
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 200);")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Centered framed panel
        self.panel = QFrame(self)
        self.panel.setStyleSheet(
            f"QFrame {{ background-color: {constants.COLOR_BG_DARKER}; "
            f"border: 2px solid {constants.COLOR_PRIMARY}; }}"
        )
        panel_w = max(520, int(self.width() * 0.78))
        panel_h = max(360, int(self.height() * 0.82))
        self.panel.setGeometry(
            (self.width() - panel_w) // 2,
            (self.height() - panel_h) // 2,
            panel_w,
            panel_h,
        )

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(18, 14, 18, 16)
        panel_layout.setSpacing(10)

        # Header row: title + close X
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("INSTRUCTIONS")
        title_font = QFont(constants.load_sinclair_font(), 16, QFont.Weight.Bold)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        title.setFont(title_font)
        title.setStyleSheet(
            f"color: {constants.COLOR_PRIMARY}; background: transparent; border: none;"
        )

        close_x = QPushButton("X")
        close_x.setFixedSize(28, 28)
        close_x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_x.setStyleSheet(
            f"QPushButton {{ background-color: transparent; "
            f"color: {constants.COLOR_PRIMARY}; "
            f"border: 2px solid {constants.COLOR_PRIMARY}; "
            f"font-family: Consolas, monospace; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {constants.COLOR_PRIMARY}; "
            f"color: {constants.COLOR_BG_DARKER}; }}"
        )
        close_x.clicked.connect(self.dismiss)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_x)
        panel_layout.addLayout(header)

        # Body: scrolling text browser with rendered HTML
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(
            f"QTextBrowser {{ background-color: {constants.COLOR_BG_DARK}; "
            f"color: {constants.COLOR_TEXT_LIGHT}; "
            f"border: 1px solid {constants.COLOR_PRIMARY}; "
            f"padding: 12px; }}"
            f"QScrollBar:vertical {{ background: {constants.COLOR_BG_DARK}; width: 10px; }}"
            f"QScrollBar::handle:vertical {{ background: {constants.COLOR_PRIMARY}; "
            f"min-height: 24px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        self.browser.setHtml(instructions_text_to_html(instructions_text))
        panel_layout.addWidget(self.browser, 1)

        # Footer dismiss button
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch()
        got_it = QPushButton("GOT IT")
        got_it.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        got_it.setFixedHeight(34)
        got_it.setMinimumWidth(140)
        got_it.setStyleSheet(
            f"QPushButton {{ background-color: transparent; "
            f"color: {constants.COLOR_PRIMARY}; "
            f"border: 2px solid {constants.COLOR_PRIMARY}; "
            f"font-family: Consolas, monospace; font-weight: bold; "
            f"letter-spacing: 2px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ background-color: {constants.COLOR_PRIMARY}; "
            f"color: {constants.COLOR_BG_DARKER}; }}"
        )
        got_it.clicked.connect(self.dismiss)
        footer.addWidget(got_it)
        footer.addStretch()
        panel_layout.addLayout(footer)

        self.setFocus()

    def dismiss(self):
        self.closed.emit()
        self.hide()
        self.deleteLater()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Click outside the panel dismisses the overlay.
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.dismiss()
        else:
            super().mousePressEvent(event)


class LauncherProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50) 
        
        self.percentage = 0.0
        self.status_text = "AWAITING ORDERS..."
        
        # Offsets
        self.anim_offset_se = 0.0
        self.anim_offset_enemy = 0.0
        
        # Dimensions
        self.PROGBAR_HEIGHT = 16
        self.GAP_TOTAL = 14
        self.TRI_W, self.TRI_H = 7, 10
        self.CHEV_W, self.CHEV_THICK, self.CHEV_SPACE = 5, 6, 8
        self.STRIPE_W, self.STRIPE_SPACE, self.STRIPE_ANGLE = 5, 6, 32
        self.PAD = 2
        
        # FG colors
        self.se_bg, self.se_fg = QColor("#8BCCDF"), QColor("#78AFBE")
        # BG colors
        self.enemy_bg, self.enemy_fg = QColor("#7B7772"), QColor("#625D5A")
        
        self.marker_color = QColor(constants.COLOR_PRIMARY)
        self.text_color = QColor(constants.COLOR_TEXT_WARN)
        self.label_color = QColor(constants.COLOR_TEXT_LIGHT)
        
        # Caches the font
        self.text_font = QFont(constants.load_sinclair_font(), 13, QFont.Weight.Medium)
        self.text_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_animation)
        self.elapsed_timer = QElapsedTimer()
        self.last_time = 0

    def start_anim(self):
        self.elapsed_timer.start()
        self.last_time = 0
        self.timer.start(16)

    def advance_animation(self):
        current_time = self.elapsed_timer.elapsed()
        dt = 16.0 if self.last_time == 0 else float(current_time - self.last_time)
        self.last_time = current_time
        multiplier = dt / 30.0 
        
        self.anim_offset_se = (self.anim_offset_se + (0.5 * multiplier)) % 10000
        self.anim_offset_enemy = (self.anim_offset_enemy + (0.125 * multiplier)) % 10000
        self.update()

    def update_progress(self, pct, text):
        self.percentage = max(0.0, min(100.0, pct))
        self.status_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Leave a little room on the right side for the % text
        bar_w = self.width() - 150 
        bar_h = self.PROGBAR_HEIGHT
        cy = self.height() - bar_h - 4 
        
        # Calculate where the green triangle marker should be based on the percentage
        raw_split_x = bar_w * (self.percentage / 100.0)
        marker_x = max(self.GAP_TOTAL / 2, min(bar_w - self.GAP_TOTAL / 2, raw_split_x))

        # Define the two halves of the bar
        left_rect = QRectF(0, cy, marker_x - (self.GAP_TOTAL / 2), bar_h)
        right_rect = QRectF(marker_x + (self.GAP_TOTAL / 2), cy, bar_w - (marker_x + (self.GAP_TOTAL / 2)), bar_h)

        # Draws progbar foreground
        if left_rect.width() > 0:
            painter.fillRect(left_rect, self.se_bg)
            clip_rect = left_rect.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
            
            if clip_rect.width() > 0 and clip_rect.height() > 0:
                painter.setClipRect(clip_rect)
                step = self.CHEV_W + self.CHEV_SPACE
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.se_fg)
                
                # Draws the repeating chevron pattern
                current_x = clip_rect.left() - step + (self.anim_offset_se % step)
                while current_x < clip_rect.right() + step:
                    poly = QPolygonF([
                        QPointF(current_x, clip_rect.top()),
                        QPointF(current_x + self.CHEV_W, clip_rect.center().y()),
                        QPointF(current_x, clip_rect.bottom()),
                        QPointF(current_x - self.CHEV_THICK, clip_rect.bottom()),
                        QPointF(current_x + self.CHEV_W - self.CHEV_THICK, clip_rect.center().y()),
                        QPointF(current_x - self.CHEV_THICK, clip_rect.top())
                    ])
                    painter.drawPolygon(poly)
                    current_x += step
                painter.setClipping(False)

        # Draws the progbar background
        if right_rect.width() > 0:
            painter.fillRect(right_rect, self.enemy_bg)
            clip_rect = right_rect.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
            
            if clip_rect.width() > 0 and clip_rect.height() > 0:
                painter.setClipRect(clip_rect)
                painter.setPen(QPen(self.enemy_fg, float(self.STRIPE_W), Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                
                painter.save()
                painter.translate(clip_rect.center().x(), clip_rect.center().y())
                painter.rotate(-self.STRIPE_ANGLE) 
                
                step = float(self.STRIPE_W + self.STRIPE_SPACE)
                diag = float(math.hypot(bar_w, bar_h)) + 50.0
                current_x = -diag - (self.anim_offset_enemy % step)
                
                while current_x < diag:
                    painter.drawLine(QLineF(current_x, -diag, current_x, diag))
                    current_x += step
                painter.restore()
                painter.setClipping(False)

        # Draws the green triangle
        poly_tri = QPolygonF([
            QPointF(marker_x - (self.TRI_W / 2.0), cy + (bar_h / 2.0) - (self.TRI_H / 2.0)),
            QPointF(marker_x + (self.TRI_W / 2.0), cy + (bar_h / 2.0)),
            QPointF(marker_x - (self.TRI_W / 2.0), cy + (bar_h / 2.0) + (self.TRI_H / 2.0))
        ])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.marker_color) 
        painter.drawPolygon(poly_tri)

        # Renders the text
        painter.setFont(self.text_font)
        fm = QFontMetrics(self.text_font)
        
        # Centers the status message above the progbar
        painter.setPen(self.label_color) 
        text_w = fm.horizontalAdvance(self.status_text)
        painter.drawText(int((bar_w / 2) - (text_w / 2)), int(cy - 8), self.status_text)

        # Renders the progress percentage
        painter.setPen(self.text_color)
        pct_text = f"{self.percentage:.7f}%".ljust(17, ' ')[:17]
        painter.drawText(int(bar_w + 15), int(cy + (bar_h / 2) + (fm.ascent() / 2) - 2), pct_text)