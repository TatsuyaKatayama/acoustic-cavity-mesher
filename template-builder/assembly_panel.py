"""Qt assembly tree and per-occurrence visibility for an AIS view."""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QSplitter, QTreeWidget, QTreeWidgetItem


class AssemblyPanel(QSplitter):
    def __init__(self, view, nodes):
        super().__init__(Qt.Orientation.Horizontal)
        self.view = view
        self.isolated_part = None
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["アセンブリ / 部品", "配置ID"])
        self.tree.setColumnWidth(0, 235)
        self.tree.setMinimumWidth(220)
        root = QTreeWidgetItem(self.tree, ["全体"])
        root.setFlags(root.flags() | Qt.ItemFlag.ItemIsAutoTristate)
        root.setCheckState(0, Qt.CheckState.Checked)
        items = {}
        self.parts = {}
        for node in nodes:
            part_id = node["id"]
            assembly = node["kind"] == "assembly"
            name = node["definition_name"] if assembly else node["name"]
            parent = items[node["parent_id"]] if node["parent_id"] is not None else root
            item = QTreeWidgetItem(parent, [name or node["name"] or part_id, part_id])
            item.setCheckState(0, Qt.CheckState.Checked)
            if assembly:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            else:
                self.parts[part_id] = item
            items[part_id] = item
        self.tree.expandAll()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh_visibility)
        self.tree.itemChanged.connect(lambda *_: self.refresh_timer.start(0))
        self.addWidget(self.tree)
        self.addWidget(view)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)
        self.setCollapsible(0, False)
        self.setCollapsible(1, False)
        self.setSizes([300, 720])

    def isolate(self, part_id):
        self.isolated_part = part_id
        self.refresh_visibility()

    def refresh_visibility(self):
        visible = {
            part_id for part_id, item in self.parts.items()
            if item.checkState(0) == Qt.CheckState.Checked
        }
        if self.isolated_part is not None:
            visible.intersection_update({self.isolated_part})
        self.view.show_parts(visible)
