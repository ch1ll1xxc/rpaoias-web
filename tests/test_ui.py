"""Smoke-тесты реального Qt. Без установленного PySide6 модуль пропускается.

На машине без дисплея: QT_QPA_PLATFORM=offscreen uv run --extra gui pytest.
Пропуск этих тестов не является подтверждением работоспособности графики.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Для проверки GUI установи extra gui")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rpaoias.examples import example_source  # noqa: E402
from rpaoias.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    widget = MainWindow()
    yield widget
    widget.editor.document().setModified(False)
    widget.close()
    app.processEvents()


def test_initial_state_step_and_reset(window):
    assert window.cpu.steps == 0
    window.step_button.click()
    assert window.cpu.steps == 1
    assert "MOV R0" in window.instruction_text.toPlainText()
    window.reset_button.click()
    assert window.cpu.steps == 0 and window.cpu.registers == [0] * 16


def test_modified_source_must_be_reassembled(window):
    window.editor.appendPlainText("; changed")
    assert not window.step_button.isEnabled()
    window.assemble_button.click()
    assert window.step_button.isEnabled()


def test_timer_run_can_be_paused(window):
    window.speed.setValue(100)
    window.start_run()
    QTest.qWait(80)
    window.pause()
    steps = window.cpu.steps
    assert steps > 0
    QTest.qWait(50)
    assert window.cpu.steps == steps


def test_dot_product_shown_in_ui(window):
    window.editor.setPlainText(example_source("dot_product"))
    window.assemble_source()
    for _ in range(200):
        if window.cpu.halted:
            break
        window.step_once()
    assert window.cpu.halted
    assert "2947418113" in window.result_label.text()


def test_fault_is_visible_and_does_not_commit(window):
    window.editor.setPlainText("MOV R0,3\nMOV R1,[R0]\nHALT")
    window.assemble_source()
    window.step_once()
    before = window.cpu.snapshot()
    window.step_once()
    assert window.cpu.snapshot() == before
    assert window.faulted
    assert "Ошибка" in window.error_label.text()
    assert not window.step_button.isEnabled()
