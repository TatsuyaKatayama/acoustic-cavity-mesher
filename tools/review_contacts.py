"""Review multiple contact candidates in AIS and save a B2 draft."""

import argparse
from pathlib import Path

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from assembly_panel import AssemblyPanel
from b2_faces import load_scene, write_json
from b2_review import open_review, validate_decision
from review_faces import FaceView, VIEW_CONTROLS


DECISIONS = {"pending": "未確認", "accepted": "採用", "rejected": "除外"}


class ContactReview(QWidget):
    def __init__(self, parts, candidates, draft, path, *, nodes):
        super().__init__()
        self.parts = parts
        self.candidates = candidates
        self.draft = draft
        self.path = path
        self.row = -1
        self.pair = []
        self.loading = False
        self.dirty = False
        self.setWindowTitle("B2 接合候補レビュー")
        self.resize(1280, 730)
        self.view = FaceView(parts)
        self.assembly = AssemblyPanel(self.view, nodes)
        self.picker = QComboBox()
        for index in range(len(candidates)):
            self.picker.addItem(self.candidate_label(index))
        self.picker.currentIndexChanged.connect(self.choose)
        self.faces = QLabel()
        self.status = QLabel()
        self.side = QComboBox()
        self.side.addItems(["ツリーの表示設定", "1面目の部品のみ", "2面目の部品のみ"])
        self.side.currentIndexChanged.connect(self.show_side)
        self.replace_side = QComboBox()
        self.replace_side.addItems(["面選択モード", "1面目をクリックで差し替え", "2面目をクリックで差し替え"])
        self.view.face_clicked.connect(self.replace_face)
        self.decision = QComboBox()
        for key, label in DECISIONS.items():
            self.decision.addItem(label, key)
        self.mode = QComboBox()
        self.mode.addItem("塞ぐ", "close")
        self.mode.addItem("隙間を残す", "keep_gap")
        self.target = QDoubleSpinBox()
        self.tolerance = QDoubleSpinBox()
        for box in (self.target, self.tolerance):
            box.setDecimals(6)
            box.setRange(0, 1_000_000)
            box.setSuffix(" mm")
            box.valueChanged.connect(self.changed)
        self.decision.currentIndexChanged.connect(self.changed)
        self.mode.currentIndexChanged.connect(self.changed)
        self.notes = QLineEdit(draft["simplification_notes"])
        self.notes.setPlaceholderText("残す小形状や簡略化方針をB3へ伝える")
        self.notes.textChanged.connect(self.changed)
        save = QPushButton("レビュー保存")
        save.clicked.connect(self.save)
        revert = QPushButton("候補の変更を戻す")
        revert.clicked.connect(lambda: self.load_row(self.row))
        fit = QPushButton("表示範囲に合わせる")
        fit.clicked.connect(self.view.fit)
        viewing = QHBoxLayout()
        for widget in (self.side, self.replace_side, fit, self.faces):
            viewing.addWidget(widget)
        conditions = QHBoxLayout()
        for widget in (
            self.decision, self.mode, QLabel("目標隙間"), self.target,
            QLabel("±許容差"), self.tolerance, save, revert,
        ):
            conditions.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.addWidget(self.picker)
        layout.addWidget(self.assembly, 1)
        layout.addWidget(QLabel(VIEW_CONTROLS))
        layout.addLayout(viewing)
        layout.addLayout(conditions)
        layout.addWidget(self.notes)
        layout.addWidget(self.status)

    def candidate_label(self, index):
        pair, gap, area = self.candidates[index]
        first, second = (face[0] for face in pair)
        decision = DECISIONS[self.draft["reviews"][index]["decision"]]
        return f"{index + 1} | {decision} | {first} ↔ {second} | 提案時の隙間 {gap:.6g} mm | 重なり {area:.6g} mm²"

    def choose(self, index):
        if self.dirty:
            with QSignalBlocker(self.picker):
                self.picker.setCurrentIndex(self.row)
            self.status.setText("現在の候補を保存するか、変更を戻してから切り替えてください。")
            return
        self.load_row(index)

    def load_row(self, index):
        self.loading = True
        self.row = index
        self.side.setCurrentIndex(0)
        self.replace_side.setCurrentIndex(0)
        self.pair = []
        if index >= 0:
            item = self.draft["reviews"][index]
            self.pair = [tuple(face) for face in item["faces"]]
            self.decision.setCurrentIndex(self.decision.findData(item["decision"]))
            condition = item["condition"] or {}
            self.mode.setCurrentIndex(self.mode.findData(condition.get("mode", "close")))
            self.target.setValue(condition.get("target_gap_mm", 0))
            self.tolerance.setValue(condition.get("tolerance_mm", 0))
        self.notes.setText(self.draft["simplification_notes"])
        self.loading = self.dirty = False
        self.update_controls()
        self.update_faces()
        pending = sum(item["decision"] == "pending" for item in self.draft["reviews"])
        self.status.setText(f"未確認 {pending} 件 / 候補 {len(self.candidates)} 件")

    def update_controls(self):
        active = self.row >= 0
        accepted = active and self.decision.currentData() == "accepted"
        self.decision.setEnabled(active)
        self.mode.setEnabled(accepted)
        self.target.setEnabled(accepted and self.mode.currentData() == "keep_gap")
        self.tolerance.setEnabled(accepted)
        self.side.setEnabled(active)
        self.replace_side.setEnabled(active)

    def changed(self):
        if not self.loading:
            self.dirty = True
            self.update_controls()
            self.status.setText("未保存の変更があります。")

    def update_faces(self):
        self.view.color_pair(self.pair)
        self.faces.setText(" ↔ ".join(f"{part_id} 面 {index}" for part_id, index in self.pair))

    def show_side(self, index):
        self.assembly.isolate(self.pair[index - 1][0] if index and self.pair else None)

    def replace_face(self, part_id, face_index):
        side = self.replace_side.currentIndex()
        if not side or self.row < 0:
            return
        candidate = self.pair.copy()
        candidate[side - 1] = (part_id, face_index)
        if candidate[0][0] == candidate[1][0]:
            self.status.setText("両面には異なる部品を指定してください。")
            return
        self.pair = candidate
        self.replace_side.setCurrentIndex(0)
        self.show_side(self.side.currentIndex())
        self.update_faces()
        self.changed()

    def save(self):
        draft = {**self.draft, "simplification_notes": self.notes.text(), "reviews": self.draft["reviews"].copy()}
        try:
            if self.row >= 0:
                decision = self.decision.currentData()
                condition = None
                if decision == "accepted":
                    mode = self.mode.currentData()
                    condition = {
                        "mode": mode,
                        "target_gap_mm": self.target.value() if mode == "keep_gap" else 0,
                        "tolerance_mm": self.tolerance.value(),
                    }
                item = {
                    "candidate_id": self.row + 1, "faces": self.pair,
                    "decision": decision, "condition": condition,
                }
                validate_decision(item, self.parts)
                draft["reviews"][self.row] = item
            write_json(self.path, draft)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        self.draft = draft
        if self.row >= 0:
            self.picker.setItemText(self.row, self.candidate_label(self.row))
        self.load_row(self.row)
        self.status.setText(f"保存済み | {self.status.text()}")

    def closeEvent(self, event):
        if self.dirty and QMessageBox.question(
            self, "未保存の変更", "保存していない変更を破棄して閉じますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        event.accept()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("review", type=Path, help="Draft JSON to open or save")
    args = parser.parse_args()
    try:
        digest, parts, nodes = load_scene(args.bundle)
        candidates, draft = open_review(digest, parts, args.candidates, args.review)
        app = QApplication([])
        review = ContactReview(parts, candidates, draft, args.review, nodes=nodes)
        review.show()
        app.processEvents()
        review.view.initialize()
        review.load_row(review.picker.currentIndex())
        return app.exec()
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Contact review failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
