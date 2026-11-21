"""Review and save a single pair of CAD faces using OCCT AIS on Windows."""

import argparse
import ctypes
from pathlib import Path

from OCP.AIS import AIS_ColoredShape, AIS_InteractiveContext, AIS_Shape
from OCP.Aspect import Aspect_DisplayConnection
from OCP.OpenGl import OpenGl_GraphicDriver
from OCP.Quantity import Quantity_Color, Quantity_NOC_GRAY70, Quantity_NOC_ORANGE
from OCP.TopAbs import TopAbs_FACE
from OCP.V3d import V3d_Viewer
from OCP.WNT import WNT_Window
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from b2_faces import load_pair, load_parts, save_pair


def window_handle_capsule(widget):
    # OCP binds the native HWND as a capsule and Qt exposes it as an integer.
    make_capsule = ctypes.pythonapi.PyCapsule_New
    make_capsule.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
    make_capsule.restype = ctypes.py_object
    return make_capsule(int(widget.winId()), None, None)


class FaceView(QWidget):
    face_clicked = Signal(str, int)

    def __init__(self, parts):
        super().__init__()
        self.parts = parts
        self.context = None
        self.view = None
        self.objects = {}
        self.colored = set()
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def initialize(self):
        self.driver = OpenGl_GraphicDriver(Aspect_DisplayConnection())
        self.viewer = V3d_Viewer(self.driver)
        self.viewer.SetDefaultLights()
        self.viewer.SetLightOn()
        self.context = AIS_InteractiveContext(self.viewer)
        self.view = self.viewer.CreateView()
        self.window = WNT_Window(window_handle_capsule(self))
        self.view.SetWindow(self.window)
        face_mode = AIS_Shape.SelectionMode_s(TopAbs_FACE)
        for part_id, (shape, _) in self.parts.items():
            presentation = AIS_ColoredShape(shape)
            self.objects[part_id] = presentation
            presentation.SetColor(Quantity_Color(Quantity_NOC_GRAY70))
            self.context.Display(presentation, 1, face_mode, False)
        self.fit()

    def paintEngine(self):
        return None

    def paintEvent(self, event):
        if self.view is not None:
            self.view.Redraw()

    def resizeEvent(self, event):
        if self.view is not None:
            self.view.MustBeResized()

    def fit(self):
        if self.view is None:
            return
        self.view.FitAll()
        self.view.ZFitAll()
        self.view.Redraw()

    def color_pair(self, pair):
        changed = self.colored | {part_id for part_id, _ in pair}
        for part_id in changed:
            self.objects[part_id].ClearCustomAspects()
        for part_id, index in pair:
            face = self.parts[part_id][1].FindKey(index)
            self.objects[part_id].SetCustomColor(face, Quantity_Color(Quantity_NOC_ORANGE))
        for part_id in changed:
            self.context.Redisplay(self.objects[part_id], False)
        self.colored = {part_id for part_id, _ in pair}
        self.view.Redraw()

    def pick(self, x, y):
        self.context.MoveTo(x, y, self.view, False)
        if self.context.HasDetectedShape():
            face = self.context.DetectedShape()
            owner = self.context.DetectedInteractive()
            for part_id, presentation in self.objects.items():
                if presentation == owner:
                    index = self.parts[part_id][1].FindIndex(face)
                    if index:
                        return part_id, index
        return None

    def mouse_xy(self, event):
        point = event.position()
        scale = self.devicePixelRatioF()
        return round(point.x() * scale), round(point.y() * scale)

    def mousePressEvent(self, event):
        if self.view is None:
            return
        x, y = self.mouse_xy(event)
        if event.button() == Qt.MouseButton.RightButton:
            self.view.StartRotation(x, y)
        elif event.button() == Qt.MouseButton.LeftButton:
            face = self.pick(x, y)
            if face is not None:
                self.face_clicked.emit(*face)

    def mouseMoveEvent(self, event):
        if self.view is not None and event.buttons() & Qt.MouseButton.RightButton:
            self.view.Rotation(*self.mouse_xy(event))

    def wheelEvent(self, event):
        if self.view is not None:
            self.view.SetZoom(1.15 ** (event.angleDelta().y() / 120))


class Review(QWidget):
    def __init__(self, parts, digest, path):
        super().__init__()
        self.digest = digest
        self.path = path
        self.parts = parts
        self.pair = load_pair(path, digest, parts) if path.exists() else []
        self.setWindowTitle("B2 接合面レビュー")
        self.resize(920, 660)
        self.view = FaceView(parts)
        self.status = QLabel()
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.save)
        clear = QPushButton("選択をクリア")
        clear.clicked.connect(self.clear)
        fit = QPushButton("全体表示")
        fit.clicked.connect(self.view.fit)
        self.view.face_clicked.connect(self.select)
        controls = QHBoxLayout()
        for button in (fit, clear, self.save_button):
            controls.addWidget(button)
        controls.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status)
        layout.addLayout(controls)

    def update_pair(self):
        self.view.color_pair(self.pair)
        label = "  ↔  ".join(f"{part_id} 面 {index}" for part_id, index in self.pair)
        self.status.setText(label or "別々の部品から面を選択してください。右ドラッグで回転、ホイールで拡大・縮小。")
        self.save_button.setEnabled(len(self.pair) == 2)

    def select(self, part_id, index):
        if len(self.pair) == 2 or (self.pair and self.pair[0][0] == part_id):
            self.pair.clear()
        self.pair.append((part_id, index))
        self.update_pair()

    def clear(self):
        self.pair.clear()
        self.update_pair()

    def save(self):
        try:
            save_pair(self.path, self.digest, self.pair, self.parts)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "保存エラー", str(error))
            return
        if "保存済み" not in self.status.text():
            self.status.setText(f"{self.status.text()}  |  保存済み")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="B1 extraction directory")
    parser.add_argument("pair", type=Path, help="JSON face pair to open or save")
    args = parser.parse_args()
    try:
        digest, parts = load_parts(args.bundle)
        app = QApplication([])
        review = Review(parts, digest, args.pair)
        review.show()
        app.processEvents()
        review.view.initialize()
        review.update_pair()
        return app.exec()
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Face review failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
