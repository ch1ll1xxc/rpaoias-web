"""Проверки обновленной темы. Заменяют проверки удаленного баннера старой версии."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Для проверки темы нужен extra gui")

from PySide6.QtWidgets import QApplication  # noqa: E402

from rpaoias.ui.window import MainWindow  # noqa: E402


def test_theme_and_flag_chips():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert "#FFF6F8" in window.styleSheet()
        window.editor.setPlainText("MOV R0,65535\nADD R0,1\nHALT")
        window.assemble_source()
        window.step_once()
        window.step_once()
        assert window.flag_labels["cf"].property("active") is True
        window.reset_cpu()
        assert window.flag_labels["cf"].property("active") is False
    finally:
        window.editor.document().setModified(False)
        window.close()
        app.processEvents()
