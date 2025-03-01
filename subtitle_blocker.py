import sys
import ctypes
from PyQt5.QtWidgets import (QApplication, QWidget, QMenu, QAction,
                             QVBoxLayout, QSlider, QLabel, QSystemTrayIcon)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize
from PyQt5.QtGui import QPainter, QColor, QCursor, QMouseEvent, QWheelEvent, QIcon
from PyQt5.QtWidgets import QGraphicsBlurEffect, QGraphicsScene, QGraphicsView, QGraphicsPixmapItem
from PyQt5.QtGui import QPixmap, QScreen
import numpy as np
from PIL import Image, ImageFilter
from io import BytesIO


class SubtitleBlocker(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(600, 100)  # Default size

        # Get screen size for positioning
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        self.screen_width = screen_geometry.width()
        self.screen_height = screen_geometry.height()

        # Position at bottom center of screen initially (where subtitles usually appear)
        self.move(int((self.screen_width - self.width()) / 2),
                  int(self.screen_height - self.height() - 50))

        # Initialize variables
        self.opacity = 0.7  # Default opacity (0.0 to 1.0)
        self.dragging = False
        self.resizing = False
        self.resize_edge = None
        self.drag_position = None
        self.resize_handle_size = 15  # Size of invisible resize handles
        self.border_color = QColor(255, 140, 0)  # Orange border
        self.border_width = 2
        self.blur_radius = 10  # Gaussian blur radius

        # Create context menu
        self.context_menu = QMenu(self)
        self.setup_menu()

        # Initialize system tray
        self.setup_tray()

        # Background screenshot (to be updated during paint events)
        self.background_pixmap = None

        # Keep reference to help dialog
        self.help_dialog = None

        self.setMouseTracking(True)  # Track mouse movements for resize cursor
        self.show()

    def setup_menu(self):
        # Create context menu actions
        self.opacity_action = QAction("Opacity: 70%", self)
        self.opacity_action.setEnabled(False)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)

        help_action = QAction("Help", self)
        help_action.triggered.connect(self.show_help)

        self.context_menu.addAction(self.opacity_action)
        self.context_menu.addSeparator()
        self.context_menu.addAction(help_action)
        self.context_menu.addAction(exit_action)

    def setup_tray(self):
        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme("application-x-executable"))
        self.tray_icon.setContextMenu(self.context_menu)
        self.tray_icon.show()
        self.tray_icon.setToolTip("Subtitle Blocker")

    def show_help(self):
        if self.help_dialog is None or not self.help_dialog.isVisible():
            help_text = """
            Subtitle Blocker - 使用帮助:

            - 左键点击并拖动: 移动遮挡区域
            - 左键点击同时滚动鼠标滚轮: 调整透明度
            - 鼠标移动到边缘并拖动: 调整遮挡区域大小
              * 四个角: 可同时调整宽度和高度
              * 上下边缘: 调整高度
              * 左右边缘: 调整宽度
            - 右键点击: 显示选项菜单

            功能特点:
            - 高斯模糊背景，提供更好的视觉体验
            - 边框始终可见，即使调整到最低不透明度
            - 总是保持在其他窗口之上
            - 可通过系统托盘图标快速访问
            """

            # Create a simple help dialog and store the reference
            self.help_dialog = QWidget(None, Qt.Window | Qt.WindowStaysOnTopHint)
            self.help_dialog.setWindowTitle("Subtitle Blocker Help")
            layout = QVBoxLayout()
            help_label = QLabel(help_text)
            help_label.setTextFormat(Qt.PlainText)
            layout.addWidget(help_label)
            self.help_dialog.setLayout(layout)
            self.help_dialog.setMinimumWidth(400)
            self.help_dialog.show()

    def get_resize_edge(self, pos):
        """Determine if the cursor is on an edge for resizing"""
        x, y = pos.x(), pos.y()
        width, height = self.width(), self.height()

        # Check if cursor is on an edge
        top = y < self.resize_handle_size
        bottom = y > height - self.resize_handle_size
        left = x < self.resize_handle_size
        right = x > width - self.resize_handle_size

        # Return the edge(s) the cursor is on
        if top and left: return "topleft"
        if top and right: return "topright"
        if bottom and left: return "bottomleft"
        if bottom and right: return "bottomright"
        if top: return "top"
        if bottom: return "bottom"
        if left: return "left"
        if right: return "right"

        return None

    def update_cursor(self, edge):
        """Update the cursor based on the edge being hovered"""
        if edge in ["top", "bottom"]:
            self.setCursor(Qt.SizeVerCursor)
        elif edge in ["left", "right"]:
            self.setCursor(Qt.SizeHorCursor)
        elif edge in ["topleft", "bottomright"]:
            self.setCursor(Qt.SizeFDiagCursor)
        elif edge in ["topright", "bottomleft"]:
            self.setCursor(Qt.SizeBDiagCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        """Handle mouse press events"""
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()

            # Check if we're on a resize edge
            edge = self.get_resize_edge(event.pos())
            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.drag_position = event.globalPos()
                self.original_size = self.size()
                self.original_pos = self.pos()

        elif event.button() == Qt.RightButton:
            # Show context menu
            self.opacity_action.setText(f"Opacity: {int(self.opacity * 100)}%")
            self.context_menu.exec_(event.globalPos())

    def mouseReleaseEvent(self, event):
        """Handle mouse release events"""
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.resizing = False
            self.resize_edge = None

    def mouseMoveEvent(self, event):
        """Handle mouse move events"""
        # Update cursor when hovering over edges
        if not self.dragging and not self.resizing:
            edge = self.get_resize_edge(event.pos())
            self.update_cursor(edge)

        # Handle dragging (moving the widget)
        if self.dragging and not self.resizing and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            # Force a repaint to update the background blur
            self.update()

        # Handle resizing
        if self.resizing and self.resize_edge:
            self.handle_resize(event.globalPos())
            # Force a repaint to update the background blur
            self.update()

    def handle_resize(self, global_pos):
        """Handle resizing based on which edge is being dragged"""
        delta = global_pos - self.drag_position
        new_width = self.original_size.width()
        new_height = self.original_size.height()
        new_x = self.original_pos.x()
        new_y = self.original_pos.y()

        # Apply changes based on which edge or corner is being dragged
        if "left" in self.resize_edge:
            new_width = max(50, self.original_size.width() - delta.x())
            new_x = self.original_pos.x() + self.original_size.width() - new_width

        if "right" in self.resize_edge:
            new_width = max(50, self.original_size.width() + delta.x())

        if "top" in self.resize_edge:
            new_height = max(20, self.original_size.height() - delta.y())
            new_y = self.original_pos.y() + self.original_size.height() - new_height

        if "bottom" in self.resize_edge:
            new_height = max(20, self.original_size.height() + delta.y())

        # Apply the new size and position
        self.setGeometry(new_x, new_y, new_width, new_height)

    def wheelEvent(self, event):
        """Handle mouse wheel events to adjust opacity"""
        if self.dragging:  # Only adjust opacity when also holding left mouse button
            delta = event.angleDelta().y() / 1200.0  # Small increments
            self.opacity = max(0.1, min(1.0, self.opacity + delta))  # Minimum opacity of 0.1
            self.update()

            # Update the opacity text in the menu
            self.opacity_action.setText(f"Opacity: {int(self.opacity * 100)}%")

    def take_background_screenshot(self):
        """Take a screenshot of the area under the widget"""
        screen = QApplication.primaryScreen()
        screenshot = screen.grabWindow(0, self.x(), self.y(), self.width(), self.height())
        return screenshot

    def apply_gaussian_blur(self, pixmap):
        """Apply gaussian blur to a QPixmap"""
        # Convert QPixmap to PIL Image
        image = pixmap.toImage()
        buffer = QPixmap.fromImage(image).toImage().bits().asstring(image.byteCount())
        pil_img = Image.frombuffer('RGBA', (image.width(), image.height()), buffer, 'raw', 'BGRA', 0, 1)

        # Apply Gaussian Blur
        blurred_img = pil_img.filter(ImageFilter.GaussianBlur(radius=self.blur_radius))

        # Convert back to QPixmap
        bytes_io = BytesIO()
        blurred_img.save(bytes_io, format='PNG')
        blurred_pixmap = QPixmap()
        blurred_pixmap.loadFromData(bytes_io.getvalue())

        return blurred_pixmap

    def paintEvent(self, event):
        """Paint the widget with the desired appearance"""
        painter = QPainter(self)

        # Take a screenshot of what's under the widget
        screenshot = self.take_background_screenshot()

        # Apply gaussian blur
        blurred_pixmap = self.apply_gaussian_blur(screenshot)

        # Draw the blurred background with opacity
        painter.setOpacity(self.opacity)
        painter.drawPixmap(0, 0, blurred_pixmap)

        # Add a dark overlay for better readability
        painter.setOpacity(0.3 * self.opacity)
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        # Always draw a visible border, regardless of opacity
        painter.setOpacity(1.0)  # Full opacity for border
        pen = painter.pen()
        pen.setColor(self.border_color)
        pen.setWidth(self.border_width)
        painter.setPen(pen)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def closeEvent(self, event):
        """Handle widget close event"""
        # Make sure to also close the help dialog if it exists
        if self.help_dialog and self.help_dialog.isVisible():
            self.help_dialog.close()
        event.accept()


def is_admin():
    """Check if the script is running with admin privileges"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Don't quit when last window is closed (due to system tray)
    window = SubtitleBlocker()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()