"""Review and save a single pair of CAD faces using OCCT AIS on Windows."""

import argparse
import ctypes
from pathlib import Path

from OCP.AIS import AIS_ColoredShape, AIS_InteractiveContext, AIS_Shape
from OCP.Aspect import Aspect_DisplayConnection, Aspect_TOL_SOLID
from OCP.OpenGl import OpenGl_GraphicDriver
from OCP.Prs3d import Prs3d_LineAspect
from OCP.Quantity import Quantity_Color, Quantity_NOC_GRAY20, Quantity_NOC_GRAY70, Quantity_NOC_ORANGE
from OCP.TopAbs import TopAbs_FACE
from OCP.V3d import V3d_Viewer
from OCP.WNT import WNT_Window
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from assembly_panel import AssemblyPanel
from b2_faces import load_candidates, load_pair, load_scene, save_pair


VIEW_CONTROLS = "Ctrl＋左ドラッグで回転、Shift＋左ドラッグで移動、2本指スクロールまたは ＋／− でズーム"


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
        self.drag = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(VIEW_CONTROLS)
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
            drawer = presentation.Attributes()
            drawer.SetFaceBoundaryDraw(True)
            drawer.SetFaceBoundaryAspect(
                Prs3d_LineAspect(Quantity_Color(Quantity_NOC_GRAY20), Aspect_TOL_SOLID, 1.0)
            )
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

    def show_parts(self, visible):
        if self.context is None:
            return
        face_mode = AIS_Shape.SelectionMode_s(TopAbs_FACE)
        for part_id, presentation in self.objects.items():
            wanted = visible is None or part_id in visible
            if wanted == self.context.IsDisplayed(presentation):
                continue
            if wanted:
                self.context.Display(presentation, 1, face_mode, False)
            else:
                self.context.Erase(presentation, False)
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
        self.setFocus()
        x, y = self.mouse_xy(event)
        button = event.button()
        left = button == Qt.MouseButton.LeftButton
        modifiers = event.modifiers()
        if button == Qt.MouseButton.RightButton or (left and modifiers & Qt.KeyboardModifier.ControlModifier):
            self.drag = ("rotate", button, x, y)
            self.view.StartRotation(x, y)
        elif button == Qt.MouseButton.MiddleButton or (left and modifiers & Qt.KeyboardModifier.ShiftModifier):
            self.drag = ("pan", button, x, y)
        elif left:
            face = self.pick(x, y)
            if face is not None:
                self.face_clicked.emit(*face)

    def mouseMoveEvent(self, event):
        if self.drag is None:
            return
        mode, button, previous_x, previous_y = self.drag
        if not event.buttons() & button:
            self.drag = None
            return
        x, y = self.mouse_xy(event)
        if mode == "rotate":
            self.view.Rotation(x, y)
        else:
            self.view.Pan(x - previous_x, previous_y - y)
        self.drag = (mode, button, x, y)

    def mouseReleaseEvent(self, event):
        if self.drag is not None and event.button() == self.drag[1]:
            self.drag = None

    def wheelEvent(self, event):
        if self.view is None:
            return
        steps = event.angleDelta().y() / 120 or event.pixelDelta().y() / 60
        if steps:
            self.view.SetZoom(1.15 ** steps)
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if self.view is None:
            return
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.view.SetZoom(1.15)
        elif key == Qt.Key.Key_Minus:
            self.view.SetZoom(1 / 1.15)
        elif key == Qt.Key.Key_F:
            self.fit()
        else:
            super().keyPressEvent(event)


class Review(QWidget):
    def __init__(self, parts, digest, path, candidates=None, *, nodes):
        super().__init__()
        self.digest = digest
        self.path = path
        self.parts = parts
        self.pair = load_pair(path, digest, parts) if path.exists() else []
        self.setWindowTitle("B2 接合面レビュー")
        self.resize(1160, 680)
        self.view = FaceView(parts)
        self.assembly = AssemblyPanel(self.view, nodes)
        self.status = QLabel()
        self.candidate_picker = QComboBox()
        if candidates is not None:
            self.candidate_picker.addItem("接合候補を選択" if candidates else "条件に合う候補なし")
            for pair, gap, area in candidates:
                label = " ↔ ".join(f"{part_id} 面 {index}" for part_id, index in pair)
                self.candidate_picker.addItem(f"{label} | 隙間 {gap:.6g} mm | 重なり {area:.6g} mm²", pair)
            self.candidate_picker.currentIndexChanged.connect(self.choose_candidate)
        self.side = QComboBox()
        self.side.addItems(["ツリーの表示設定", "選択した1面目の部品だけ", "選択した2面目の部品だけ"])
        self.side.currentIndexChanged.connect(self.update_visibility)
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
        controls.addWidget(self.side)
        layout = QVBoxLayout(self)
        if candidates is not None:
            layout.addWidget(self.candidate_picker)
        layout.addWidget(self.assembly, 1)
        layout.addWidget(QLabel(VIEW_CONTROLS))
        layout.addWidget(self.status)
        layout.addLayout(controls)

    def update_pair(self):
        self.view.color_pair(self.pair)
        label = "  ↔  ".join(f"{part_id} 面 {index}" for part_id, index in self.pair)
        self.status.setText(label or "別々の部品から面を選択してください。")
        self.save_button.setEnabled(len(self.pair) == 2)
        self.side.setEnabled(len(self.pair) == 2)

    def choose_candidate(self, index):
        if index > 0:
            self.side.setCurrentIndex(0)
            self.pair = [tuple(face) for face in self.candidate_picker.itemData(index)]
            self.update_pair()

    def update_visibility(self, index):
        self.assembly.isolate(self.pair[index - 1][0] if index and len(self.pair) == 2 else None)

    def select(self, part_id, index):
        self.side.setCurrentIndex(0)
        self.candidate_picker.setCurrentIndex(0)
        if len(self.pair) == 2 or (self.pair and self.pair[0][0] == part_id):
            self.pair.clear()
        self.pair.append((part_id, index))
        self.update_pair()

    def clear(self):
        self.side.setCurrentIndex(0)
        self.candidate_picker.setCurrentIndex(0)
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
    parser.add_argument("--candidates", type=Path, help="JSON from propose_contacts.py")
    args = parser.parse_args()
    try:
        digest, parts, nodes = load_scene(args.bundle)
        candidates = load_candidates(args.candidates, digest, parts) if args.candidates else None
        app = QApplication([])
        review = Review(parts, digest, args.pair, candidates, nodes=nodes)
        review.show()
        app.processEvents()
        review.view.initialize()
        review.update_pair()
        return app.exec()
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Face review failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
