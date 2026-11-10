"""Проверки реального Qt; при отсутствии PySide6 не подменяем GUI заглушками."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="Для проверки вкладок нужен extra gui")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QSplitter  # noqa: E402

from rpaoias.ui.window import HISTORY_LIMIT, MainWindow  # noqa: E402


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


def load(window, source):
    window.editor.setPlainText(source)
    window.assemble_source()


def test_five_main_tabs_without_banner_and_splitters(window):
    assert [window.main_tabs.tabText(i) for i in range(5)] == ["Программа", "Исполнение", "Регистры", "Память", "История"]
    assert not window.findChildren(QSplitter)
    texts = "\n".join(x.text() for x in window.findChildren(QLabel))
    assert "plush.cpu" not in texts and "твоего рисунка" not in texts
    assert "plush.cpu" not in window.windowTitle()


def test_assembly_diagnostic_is_visible_and_does_not_replace_source(window):
    load(window, "ADD R0,[R1]")
    assert not window.error_label.isHidden()
    assert "Ошибка" in window.diagnostics.toPlainText()
    assert window.editor.toPlainText() == "ADD R0,[R1]"
    assert not window.step_button.isEnabled()


def test_record_replay_does_not_execute_cpu(window):
    load(window, "MOV R0,7\nHALT")
    window.step_once()
    before, memory = window.cpu.snapshot(), window.cpu.memory.image()
    window.step_view.replay()
    for _ in range(4):
        window.step_view._advance()
    assert window.cpu.snapshot() == before
    assert window.cpu.memory.image() == memory
    assert not window.step_view.timer.isActive()
    assert window.step_view.phase_index == 3


def test_older_history_can_be_opened_without_rolling_back(window):
    load(window, "MOV R0,7\nADD R0,1\nHALT")
    for _ in range(3):
        window.step_once()
    before = window.cpu.snapshot()
    window.open_history(0)
    assert window.history_view.record.result.after.registers[0] == 7
    assert window.cpu.registers[0] == 8 and window.cpu.halted
    assert window.cpu.snapshot() == before
    assert "Архивный шаг 1" in window.history_view.caption.text()


def test_fault_not_added_as_successful_history_step(window):
    load(window, "MOV R0,3\nMOV R1,[R0]\nHALT")
    window.step_once()
    snapshot = window.cpu.snapshot()
    window.step_once()
    assert window.cpu.snapshot() == snapshot
    assert len(window.records) == 1
    assert window.faulted
    assert not window.error_label.isHidden()
    assert not window.editor.extraSelections()


def test_reset_clears_history_and_stops_replay(window):
    window.step_once()
    window.step_view.replay()
    window.open_history(0)
    window.history_view.replay()
    window.reset_cpu()
    assert not window.records
    assert window.history_table.rowCount() == 0
    assert not window.step_view.timer.isActive()
    assert not window.history_view.timer.isActive()
    assert window.step_view.record is None


def test_register_tab_refreshes_after_hidden_execution(window):
    load(window, "MOV R0,7\nHALT")
    window.step_once()
    window.main_tabs.setCurrentIndex(2)
    assert window.register_table.item(0, 1).text() == "0x0007"
    assert window.register_table.item(0, 1).font().bold()
    assert window.special_table.item(0, 1).text() == "0x0004"


def test_result_button_and_odd_address_go_to_word(window):
    window.show_result_memory()
    assert window.main_tabs.currentIndex() == 3
    assert window.memory_tabs.currentIndex() == 0
    assert window.memory_page.currentData() == 0x0500
    window.go_to_address(0x0503)
    assert window.memory_table.currentRow() == 1
    assert window.memory_table.item(1, 0).text() == "0x0502"


def test_access_log_includes_reads_and_writes_and_filters_fetch(window):
    load(window, "MOV R1,[data]\nMOV [data+2],R1\nHALT\n.org 256\ndata: .word 7,0")
    window.step_once()
    window.step_once()
    window.main_tabs.setCurrentIndex(3)
    window.memory_tabs.setCurrentIndex(2)
    assert window.access_table.rowCount() == 2
    window.show_fetch.setChecked(True)
    assert window.access_table.rowCount() == 4
    window.step_once()
    assert window.access_table.rowCount() == 5
    window._refresh_accesses()
    assert window.access_table.rowCount() == 5
    window.show_fetch.setChecked(False)
    assert window.access_table.rowCount() == 2


def test_halt_keeps_executed_instruction_and_clears_pc_highlight(window):
    load(window, "MOV R0,4\nHALT")
    window.step_once()
    assert "MOV R0" in window.instruction_text.toPlainText()
    window.step_once()
    assert window.cpu.pc == 8
    assert "HALT" in window.instruction_text.toPlainText()
    assert not window.editor.extraSelections()
    assert not window.listing.selectedItems()


def test_modified_machine_code_not_mislabeled_with_old_source(window):
    load(window, "MOV R0,0xFF00\nMOV [target+2],R0\nJMP target\ntarget: NOP\nHALT")
    for _ in range(3):
        window.step_once()
    assert not window.editor.extraSelections()
    window.step_once()
    assert window.last_description.source == ""
    assert window.step_view.command.text() == "HALT"


def test_long_run_has_bounded_history(window):
    load(window, "loop: JMP loop")
    for _ in range(HISTORY_LIMIT + 7):
        window.step_once()
    assert len(window.records) == HISTORY_LIMIT
    assert window.history_table.rowCount() == HISTORY_LIMIT
    assert window.records[0].result.after.steps == 8
    assert window.history_table.item(0, 0).data(Qt.ItemDataRole.UserRole).result.after.steps == 8


@pytest.mark.parametrize("width,height", [(1200, 830), (960, 700), (700, 560)])
def test_tabs_can_be_shown_at_small_window_sizes(window, app, width, height):
    window.resize(width, height)
    window.show()
    for index in range(window.main_tabs.count()):
        window.main_tabs.setCurrentIndex(index)
        app.processEvents()
        assert window.main_tabs.currentWidget().isVisible()
        assert window.main_tabs.currentWidget().height() > 100
