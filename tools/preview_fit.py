"""Overlay a B4 fitted solid and the detailed part in the Windows AIS viewer."""

import argparse
from hashlib import sha256
from pathlib import Path

from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from b2_faces import load_parts
from b4_geometry import indexed_faces, read_brep, read_record
from review_faces import FaceView, VIEW_CONTROLS


def overlay(bundle, result):
    digest, parts = load_parts(bundle)
    record, _ = read_record(result / "fit.json")
    geometry = (result / "fitted.brep").read_bytes()
    if record["manifest_sha256"] != digest or sha256(geometry).hexdigest() != record["geometry_sha256"]:
        raise ValueError("Fitted geometry does not match the B1 bundle and B4 record")
    fitted = read_brep(geometry)
    return {"detail": parts[record["source_part_id"]], "fit": (fitted, indexed_faces(fitted))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    try:
        parts = overlay(args.bundle, args.result)
        app = QApplication([])
        window = QWidget()
        window.setWindowTitle("B4 試しフィットの重ね合わせ")
        window.resize(940, 680)
        view = FaceView(parts)
        fit = QPushButton("全体表示")
        fit.clicked.connect(view.fit)
        layout = QVBoxLayout(window)
        layout.addWidget(QLabel("灰色（半透明）＝詳細形状　青＝試しフィット"))
        layout.addWidget(view, 1)
        layout.addWidget(QLabel(VIEW_CONTROLS))
        layout.addWidget(fit)
        window.show()
        app.processEvents()
        view.initialize()
        view.context.SetTransparency(view.objects["detail"], 0.65, False)
        view.context.SetColor(view.objects["fit"], Quantity_Color(0.12, 0.4, 0.85, Quantity_TOC_RGB), True)
        return app.exec()
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Fit preview failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
