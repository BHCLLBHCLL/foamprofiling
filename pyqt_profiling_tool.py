#!/usr/bin/env python3
"""
PyQt tool for setting OpenFOAM profiling parameters
and visualizing profiling settings after each run.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False


MARKER_BEGIN = "// --- foamprofiling (auto-generated) BEGIN ---"
MARKER_END = "// --- foamprofiling (auto-generated) END ---"
HISTORY_FILE = ".foamprofiling_history.json"


@dataclass
class ProfilingConfig:
    enabled: bool = True
    interval: int = 20
    detail_level: str = "basic"
    output_dir: str = "profiling"
    source: str = "manual"
    timestamp: str = ""
    run_log: str = ""
    run_profile_line_count: int = 0


class PlotCanvas(FigureCanvasQTAgg):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        self.figure = Figure(figsize=(5, 3), tight_layout=True)
        self.ax = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)

    def plot_history(self, history: List[ProfilingConfig]) -> None:
        self.ax.clear()
        if not history:
            self.ax.set_title("No profiling settings history")
            self.draw()
            return

        x = list(range(1, len(history) + 1))
        intervals = [h.interval for h in history]
        enabled_values = [1 if h.enabled else 0 for h in history]

        self.ax.plot(x, intervals, marker="o", label="interval")
        self.ax.plot(x, enabled_values, marker="s", label="enabled(1/0)")
        self.ax.set_xlabel("snapshot")
        self.ax.set_ylabel("value")
        self.ax.set_title("Profiling settings history")
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()
        self.draw()


class ProfilingTool(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenFOAM Profiling Config Tool")
        self.resize(1080, 680)
        self.case_dir = Path.cwd()
        self.history: List[ProfilingConfig] = []

        self._build_ui()
        self._load_history()
        self._refresh_history_view()
        self._load_control_dict()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)

        # Case selector
        case_group = QtWidgets.QGroupBox("Case directory")
        case_layout = QtWidgets.QHBoxLayout(case_group)
        self.case_path_edit = QtWidgets.QLineEdit(str(self.case_dir))
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_case_dir)
        case_layout.addWidget(self.case_path_edit)
        case_layout.addWidget(browse_btn)
        root_layout.addWidget(case_group)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        root_layout.addWidget(splitter, stretch=1)

        # Left panel - config editor
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        form_group = QtWidgets.QGroupBox("Profiling settings")
        form = QtWidgets.QFormLayout(form_group)

        self.enable_check = QtWidgets.QCheckBox("Enable profiling")
        self.enable_check.setChecked(True)
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(1, 1_000_000)
        self.interval_spin.setValue(20)
        self.detail_combo = QtWidgets.QComboBox()
        self.detail_combo.addItems(["basic", "normal", "detailed"])
        self.output_dir_edit = QtWidgets.QLineEdit("profiling")

        form.addRow("Switch", self.enable_check)
        form.addRow("Interval", self.interval_spin)
        form.addRow("Detail level", self.detail_combo)
        form.addRow("Output directory", self.output_dir_edit)
        left_layout.addWidget(form_group)

        button_row = QtWidgets.QHBoxLayout()
        load_btn = QtWidgets.QPushButton("Load from controlDict")
        load_btn.clicked.connect(self._load_control_dict)
        apply_btn = QtWidgets.QPushButton("Apply to controlDict")
        apply_btn.clicked.connect(self._apply_to_control_dict)
        scan_run_btn = QtWidgets.QPushButton("Scan latest run log")
        scan_run_btn.clicked.connect(self._scan_latest_run)
        button_row.addWidget(load_btn)
        button_row.addWidget(apply_btn)
        button_row.addWidget(scan_run_btn)
        left_layout.addLayout(button_row)

        self.status_box = QtWidgets.QTextEdit()
        self.status_box.setReadOnly(True)
        self.status_box.setPlaceholderText("Status / operation logs...")
        left_layout.addWidget(self.status_box, stretch=1)

        splitter.addWidget(left)

        # Right panel - visualization and history
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.addWidget(QtWidgets.QLabel("Profiling settings history"))

        self.history_table = QtWidgets.QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ["timestamp", "source", "enabled", "interval", "detail", "output", "run log"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.history_table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        right_layout.addWidget(self.history_table, stretch=2)

        if HAS_MATPLOTLIB:
            self.plot_canvas = PlotCanvas()
            right_layout.addWidget(self.plot_canvas, stretch=3)
        else:
            self.plot_canvas = None
            notice = QtWidgets.QLabel(
                "matplotlib not found: chart disabled.\nInstall via: pip install matplotlib"
            )
            notice.setStyleSheet("color: #a22;")
            right_layout.addWidget(notice)

        splitter.addWidget(right)
        splitter.setSizes([460, 620])

    def _case_dir(self) -> Path:
        return Path(self.case_path_edit.text().strip()).resolve()

    def _control_dict_path(self) -> Path:
        return self._case_dir() / "system" / "controlDict"

    def _history_path(self) -> Path:
        return self._case_dir() / HISTORY_FILE

    def _log(self, msg: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.status_box.append(f"[{now}] {msg}")

    def _browse_case_dir(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select OpenFOAM case directory", str(self.case_dir)
        )
        if not path:
            return
        self.case_path_edit.setText(path)
        self.case_dir = Path(path)
        self._load_history()
        self._refresh_history_view()
        self._load_control_dict()
        self._log(f"Case switched to: {path}")

    def _load_control_dict(self) -> None:
        path = self._control_dict_path()
        if not path.exists():
            self._log(f"controlDict not found: {path}")
            return

        content = path.read_text(encoding="utf-8", errors="ignore")
        block = self._extract_block(content)
        if not block:
            self._log("No managed profiling block found; using current form defaults.")
            return

        cfg = self._parse_block(block)
        self.enable_check.setChecked(cfg.enabled)
        self.interval_spin.setValue(cfg.interval)
        idx = self.detail_combo.findText(cfg.detail_level)
        if idx >= 0:
            self.detail_combo.setCurrentIndex(idx)
        self.output_dir_edit.setText(cfg.output_dir)
        self._log("Loaded profiling settings from controlDict.")

    def _apply_to_control_dict(self) -> None:
        control_path = self._control_dict_path()
        if not control_path.exists():
            self._log(f"Cannot apply: missing file {control_path}")
            QtWidgets.QMessageBox.warning(
                self, "Missing file", f"controlDict not found:\n{control_path}"
            )
            return

        cfg = self._current_config(source="manual")
        block = self._build_block(cfg)
        raw = control_path.read_text(encoding="utf-8", errors="ignore")
        updated = self._upsert_block(raw, block)
        control_path.write_text(updated, encoding="utf-8")

        cfg.timestamp = datetime.now().isoformat(timespec="seconds")
        self.history.append(cfg)
        self._save_history()
        self._refresh_history_view()
        self._log(f"Applied profiling settings to {control_path}")

    def _scan_latest_run(self) -> None:
        case = self._case_dir()
        logs = sorted(case.glob("log*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            self._log("No run logs found (log*).")
            return

        latest = logs[0]
        text = latest.read_text(encoding="utf-8", errors="ignore")
        profile_lines = re.findall(r".*profil.*", text, flags=re.IGNORECASE)

        cfg = self._current_config(source="runtime-scan")
        cfg.timestamp = datetime.now().isoformat(timespec="seconds")
        cfg.run_log = latest.name
        cfg.run_profile_line_count = len(profile_lines)
        self.history.append(cfg)
        self._save_history()
        self._refresh_history_view()

        self._log(
            f"Scanned {latest.name}: found {cfg.run_profile_line_count} profiling-related lines."
        )

    def _current_config(self, source: str) -> ProfilingConfig:
        return ProfilingConfig(
            enabled=self.enable_check.isChecked(),
            interval=self.interval_spin.value(),
            detail_level=self.detail_combo.currentText(),
            output_dir=self.output_dir_edit.text().strip() or "profiling",
            source=source,
        )

    def _load_history(self) -> None:
        self.history = []
        path = self._history_path()
        if not path.exists():
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for item in raw:
                self.history.append(ProfilingConfig(**item))
        except Exception as exc:
            self._log(f"Failed to load history: {exc}")

    def _save_history(self) -> None:
        path = self._history_path()
        payload = [asdict(item) for item in self.history[-200:]]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _refresh_history_view(self) -> None:
        self.history_table.setRowCount(len(self.history))
        for row, item in enumerate(self.history):
            values = [
                item.timestamp,
                item.source,
                str(item.enabled),
                str(item.interval),
                item.detail_level,
                item.output_dir,
                item.run_log or "-",
            ]
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QtWidgets.QTableWidgetItem(value))

        if self.plot_canvas:
            self.plot_canvas.plot_history(self.history)

    @staticmethod
    def _extract_block(content: str) -> str:
        pattern = re.compile(
            re.escape(MARKER_BEGIN) + r"(.*?)" + re.escape(MARKER_END), re.DOTALL
        )
        m = pattern.search(content)
        return m.group(1).strip() if m else ""

    def _parse_block(self, block: str) -> ProfilingConfig:
        cfg = ProfilingConfig()
        patterns = {
            "enabled": r"profilingEnabled\s+(true|false);",
            "interval": r"profilingInterval\s+(\d+);",
            "detail_level": r'profilingDetailLevel\s+"([^"]+)";',
            "output_dir": r'profilingOutputDir\s+"([^"]+)";',
        }

        m = re.search(patterns["enabled"], block)
        if m:
            cfg.enabled = m.group(1).lower() == "true"
        m = re.search(patterns["interval"], block)
        if m:
            cfg.interval = int(m.group(1))
        m = re.search(patterns["detail_level"], block)
        if m:
            cfg.detail_level = m.group(1)
        m = re.search(patterns["output_dir"], block)
        if m:
            cfg.output_dir = m.group(1)
        return cfg

    @staticmethod
    def _build_block(cfg: ProfilingConfig) -> str:
        enabled = "true" if cfg.enabled else "false"
        return (
            f"{MARKER_BEGIN}\n"
            f"profilingEnabled {enabled};\n"
            f"profilingInterval {cfg.interval};\n"
            f'profilingDetailLevel "{cfg.detail_level}";\n'
            f'profilingOutputDir "{cfg.output_dir}";\n'
            f"{MARKER_END}"
        )

    @staticmethod
    def _upsert_block(content: str, new_block: str) -> str:
        pattern = re.compile(
            re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END), re.DOTALL
        )
        if pattern.search(content):
            return pattern.sub(new_block, content)
        return content.rstrip() + "\n\n" + new_block + "\n"


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("OpenFOAM Profiling Config Tool")
    app.setWindowIcon(QtGui.QIcon())
    win = ProfilingTool()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
