"""Оконный отладчик с вкладками. Исполнение остается в исходном CPU.step()."""

import csv
import re
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QColor, QKeySequence, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from rpaoias.assembler.assembler import Program, assemble
from rpaoias.cli import trace_line
from rpaoias.cpu.processor import CPU, StepResult
from rpaoias.cpu.word import MEMORY_BYTES, join_words, signed
from rpaoias.errors import EmulatorError
from rpaoias.examples import EXAMPLES, example_source
from rpaoias.isa.codec import decode
from rpaoias.ui.highlighter import AssemblyHighlighter
from rpaoias.ui.step_description import StepDescription, describe_step, flags_text
from rpaoias.ui.theme import NEXT_BG, NEXT_INK, apply_theme, fixed_font
from rpaoias.ui.widgets import StepView, cell, horizontal_scroll, label, page, table

HISTORY_LIMIT = 1000


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("РПАО ИАС | Вариант 2 | Эмулятор процессора")
        self.resize(1200, 830)
        self.program: Program | None = None
        self.cpu: CPU | None = None
        self.assembled_source = ""
        self.last_step: StepResult | None = None
        self.last_description: StepDescription | None = None
        self.current_path: Path | None = None
        self.records: deque[StepDescription] = deque(maxlen=HISTORY_LIMIT)
        self.faulted = False
        self.run_budget = 0
        self._access_last_step = 0
        self._access_filter = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        apply_theme(self)
        self._build_window()
        self._connect()
        self._update_interval()
        self.editor.setPlainText(example_source("sum"))
        self.assemble_source()

    def _build_window(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 7)
        root.setSpacing(8)
        self.setCentralWidget(central)

        controls = QFrame()
        controls.setObjectName("controls")
        row = QHBoxLayout(controls)
        row.setContentsMargins(9, 7, 9, 7)
        row.setSpacing(7)
        self.assemble_button = QPushButton("Собрать")
        self.assemble_button.setProperty("role", "primary")
        self.step_button = QPushButton("Шаг")
        self.run_button = QPushButton("Пуск")
        self.pause_button = QPushButton("Пауза")
        self.reset_button = QPushButton("Сброс CPU")
        self.speed = QSpinBox()
        self.speed.setRange(1, 100)
        self.speed.setValue(10)
        self.speed.setSuffix(" ком/с")
        self.speed.setAccessibleName("Скорость исполнения")
        self.speed.setToolTip("Темп выполнения команд через таймер, не аппаратная тактовая частота.")
        for widget in (self.assemble_button, self.step_button, self.run_button, self.pause_button, self.reset_button):
            row.addWidget(widget)
        row.addStretch()
        row.addWidget(label("Скорость", "muted"))
        row.addWidget(self.speed)
        root.addWidget(horizontal_scroll(controls))

        state = QFrame()
        state.setObjectName("state")
        state_row = QHBoxLayout(state)
        state_row.setContentsMargins(8, 5, 8, 5)
        state_row.setSpacing(6)
        self.state_label = label()
        self.state_label.setObjectName("stateText")
        self.state_label.setWordWrap(True)
        self.state_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        state_row.addWidget(self.state_label, 1)
        self.flag_labels = {}
        for name, meaning in (("zf", "Ноль"), ("sf", "Знак"), ("cf", "Перенос / заем"), ("of", "Знаковое переполнение")):
            widget = label(f"{name.upper()} 0", "flag")
            widget.setProperty("active", False)
            widget.setToolTip(meaning)
            self.flag_labels[name] = widget
            state_row.addWidget(widget)
        root.addWidget(state)

        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("mainTabs")
        self.main_tabs.setUsesScrollButtons(True)
        self._program_page()
        self._execution_page()
        self._register_page()
        self._memory_page()
        self._history_page()
        root.addWidget(self.main_tabs, 1)
        self.error_label = label()
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)
        self._menus()

    def _program_page(self) -> None:
        widget, layout = page()
        commands = QWidget()
        row = QHBoxLayout(commands)
        row.setContentsMargins(0, 0, 0, 0)
        self.example_box = QComboBox()
        for name, text in EXAMPLES.items():
            self.example_box.addItem(text, name)
        self.example_box.setMinimumWidth(195)
        self.load_button = QPushButton("Загрузить пример")
        self.open_button = QPushButton("Открыть .asm")
        self.save_button = QPushButton("Сохранить .asm")
        for control in (self.example_box, self.load_button, self.open_button, self.save_button):
            row.addWidget(control)
        row.addStretch()
        layout.addWidget(horizontal_scroll(commands))
        self.source_tabs = QTabWidget()
        self.editor = QPlainTextEdit()
        self.editor.setFont(fixed_font())
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setAccessibleName("Исходник программы")
        self.highlighter = AssemblyHighlighter(self.editor.document())
        self.listing = table(["Адрес", "Машинное слово", "Исходная команда"], widths=[100, 175, 650])
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(1000)
        self.diagnostics.setFont(fixed_font())
        self.source_tabs.addTab(self.editor, "Исходник")
        self.source_tabs.addTab(self.listing, "Листинг сборки")
        self.source_tabs.addTab(self.diagnostics, "Диагностика")
        layout.addWidget(self.source_tabs, 1)
        self.source_status = label("", "muted")
        self.source_status.setWordWrap(True)
        layout.addWidget(self.source_status)
        self.main_tabs.addTab(widget, "Программа")

    @staticmethod
    def _scroll_view(view: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        view.setMinimumHeight(520)
        area.setWidget(view)
        return area

    def _execution_page(self) -> None:
        widget, layout = page()
        self.inspector_tabs = QTabWidget()
        self.step_view = StepView()
        self.inspector_tabs.addTab(self._scroll_view(self.step_view), "Разбор шага")
        self.instruction_text = QPlainTextEdit()
        self.instruction_text.setReadOnly(True)
        self.instruction_text.setFont(fixed_font())
        self.inspector_tabs.addTab(self.instruction_text, "Поля инструкции IR")
        result_widget, result_layout = page()
        self.result_label = label()
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setFont(fixed_font())
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        result_layout.addWidget(self.result_label)
        result_layout.addStretch()
        self.inspector_tabs.addTab(result_widget, "Результат")
        layout.addWidget(self.inspector_tabs)
        self.main_tabs.addTab(widget, "Исполнение")

    def _register_page(self) -> None:
        widget, layout = page()
        self.register_tabs = QTabWidget()
        self.register_table = table(["Регистр", "HEX", "Со знаком", "Без знака"], 16, [130, 160, 220, 220])
        self.special_table = table(["Регистр", "Значение", "Назначение"], widths=[160, 220, 520])
        self.register_tabs.addTab(self.register_table, "R0–R15")
        self.register_tabs.addTab(self.special_table, "Служебные регистры и флаги")
        layout.addWidget(self.register_tabs, 1)
        layout.addWidget(label("Сиреневый фон и полужирный текст обозначают изменения на последнем шаге.", "muted"))
        self.main_tabs.addTab(widget, "Регистры")

    def _memory_page(self) -> None:
        widget, layout = page()
        self.memory_tabs = QTabWidget()
        memory, body = page()
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        self.memory_page = QComboBox()
        for address in range(0, MEMORY_BYTES, 256):
            self.memory_page.addItem(f"0x{address:04X}–0x{address + 255:04X}", address)
        self.result_memory_button = QPushButton("К RESULT")
        self.address_box = QSpinBox()
        self.address_box.setRange(0, MEMORY_BYTES - 1)
        self.address_box.setDisplayIntegerBase(16)
        self.address_box.setPrefix("0x")
        self.address_box.setAccessibleName("Адрес в единой ОЗУ")
        self.address_button = QPushButton("Перейти")
        for control in (label("Страница", "muted"), self.memory_page, self.result_memory_button,
                        label("Адрес", "muted"), self.address_box, self.address_button):
            row.addWidget(control)
        row.addStretch()
        body.addWidget(horizontal_scroll(bar))
        self.memory_table = table(["Адрес", "Байты low high", "Слово HEX", "Со знаком", "Метки"], 128, [100, 180, 150, 160, 350])
        body.addWidget(self.memory_table, 1)
        self.memory_tabs.addTab(memory, "Единая ОЗУ")
        self.symbol_table = table(["Метка", "Адрес", "Действие"], widths=[240, 150, 500])
        self.memory_tabs.addTab(self.symbol_table, "Метки")
        access_widget, access_layout = page()
        self.show_fetch = QCheckBox("Показывать выборку команд")
        self.show_fetch.setChecked(False)
        access_layout.addWidget(self.show_fetch)
        self.access_table = table(["Шаг", "Доступ", "Адрес", "Байт", "Значение", "Было"], widths=[80, 210, 120, 80, 170, 130])
        access_layout.addWidget(self.access_table, 1)
        access_layout.addWidget(label("Обращения из последних 1000 сохраненных команд. Выборка команд скрыта по умолчанию.", "muted"))
        self.memory_tabs.addTab(access_widget, "Обращения")
        layout.addWidget(self.memory_tabs)
        self.main_tabs.addTab(widget, "Память")

    def _history_page(self) -> None:
        widget, layout = page()
        bar = QHBoxLayout()
        self.history_status = label("История пуста", "muted")
        bar.addWidget(self.history_status, 1)
        self.history_open_button = QPushButton("Открыть разбор")
        self.history_export_button = QPushButton("Сохранить CSV")
        bar.addWidget(self.history_open_button)
        bar.addWidget(self.history_export_button)
        layout.addLayout(bar)
        self.history_tabs = QTabWidget()
        self.history_table = table(["Шаг", "Адрес", "Команда", "Изменения", "PC после"], widths=[75, 90, 240, 440, 120])
        self.history_view = StepView(historical=True)
        self.trace = QPlainTextEdit()
        self.trace.setReadOnly(True)
        self.trace.setFont(fixed_font())
        self.trace.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.trace.setMaximumBlockCount(HISTORY_LIMIT)
        self.history_tabs.addTab(self.history_table, "Команды")
        self.history_tabs.addTab(self._scroll_view(self.history_view), "Разбор выбранного шага")
        self.history_tabs.addTab(self.trace, "Текстовая трасса")
        layout.addWidget(self.history_tabs, 1)
        layout.addWidget(label("Двойной щелчок по строке открывает сохраненный шаг. Это просмотр без отката CPU.", "muted"))
        self.main_tabs.addTab(widget, "История")

    def _menus(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        for text, shortcut, callback in (("Открыть .asm", "Ctrl+O", self.open_source),
                                         ("Сохранить .asm", "Ctrl+S", self.save_source)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction("Выход", self.close)
        view_menu = self.menuBar().addMenu("Вкладки")
        for n in range(self.main_tabs.count()):
            action = QAction(self.main_tabs.tabText(n), self)
            action.setShortcut(QKeySequence(f"Alt+{n + 1}"))
            action.triggered.connect(lambda checked=False, index=n: self.main_tabs.setCurrentIndex(index))
            view_menu.addAction(action)
        for button, shortcut in ((self.assemble_button, "Ctrl+Return"), (self.step_button, "F10"),
                                 (self.run_button, "F5"), (self.pause_button, "Shift+F5")):
            button.setShortcut(QKeySequence(shortcut))
            button.setToolTip(shortcut)

    def _connect(self) -> None:
        for button, handler in ((self.load_button, self.load_example), (self.open_button, self.open_source),
                                (self.save_button, self.save_source), (self.assemble_button, self.assemble_source),
                                (self.reset_button, self.reset_cpu), (self.step_button, self.step_once),
                                (self.run_button, self.start_run), (self.pause_button, self.pause),
                                (self.result_memory_button, self.show_result_memory),
                                (self.address_button, lambda: self.go_to_address(self.address_box.value())),
                                (self.history_open_button, self.open_history),
                                (self.history_export_button, self.export_history)):
            button.clicked.connect(handler)
        self.speed.valueChanged.connect(self._update_interval)
        self.memory_page.currentIndexChanged.connect(self._refresh_memory)
        self.main_tabs.currentChanged.connect(self._tab_changed)
        self.memory_tabs.currentChanged.connect(self._tab_changed)
        self.show_fetch.toggled.connect(self._refresh_accesses)
        self.symbol_table.cellDoubleClicked.connect(self._symbol_clicked)
        self.history_table.cellDoubleClicked.connect(lambda row, col: self.open_history(row))
        self.editor.textChanged.connect(self._source_changed)

    def _update_interval(self, _value: int = 0) -> None:
        self.timer.setInterval(max(1, 1000 // self.speed.value()))

    def _tab_changed(self, _index: int = 0) -> None:
        if not self.cpu:
            return
        self._refresh_registers()
        self._refresh_memory()
        self._refresh_accesses()

    def _source_changed(self) -> None:
        if self.timer.isActive():
            self.pause()
        self._buttons()
        if self.program and self.editor.toPlainText() != self.assembled_source:
            self.editor.setExtraSelections([])
            self.listing.clearSelection()
        self._source_status()

    def _source_status(self) -> None:
        path = str(self.current_path) if self.current_path else "Исходник в памяти"
        state = "совпадает со сборкой" if self.editor.toPlainText() == self.assembled_source else "нужна сборка"
        self.source_status.setText(f"{path} / {state}. Розовая строка: следующая команда по PC.")

    def _buttons(self) -> None:
        running = self.timer.isActive()
        fresh = self.program is not None and self.editor.toPlainText() == self.assembled_source
        executable = fresh and self.cpu is not None and not self.cpu.halted and not self.faulted
        self.step_button.setEnabled(executable and not running)
        self.run_button.setEnabled(executable and not running)
        self.pause_button.setEnabled(running)
        self.reset_button.setEnabled(fresh and not running)
        for widget in (self.assemble_button, self.load_button, self.open_button, self.example_box):
            widget.setEnabled(not running)
        self.editor.setReadOnly(running)
        self.result_memory_button.setEnabled(bool(self.program and "RESULT" in self.program.symbols))
        self.step_view.replay_button.setEnabled(self.last_description is not None and not running)
        self.history_open_button.setEnabled(bool(self.records))
        self.history_export_button.setEnabled(bool(self.records))
        self._refresh_state()

    def _refresh_state(self) -> None:
        if self.cpu is None:
            self.state_label.setText("Собери программу для запуска")
            return
        cpu = self.cpu
        state = ("нужна сборка" if self.editor.toPlainText() != self.assembled_source else
                 "ошибка CPU" if self.faulted else "HALT" if cpu.halted else
                 "выполнение" if self.timer.isActive() else "готов к шагу")
        self.state_label.setText(f"PC 0x{cpu.pc:04X}   IR 0x{cpu.ir:08X}   Шаг {cpu.steps}   {state}")
        for name, widget in self.flag_labels.items():
            active = bool(getattr(cpu.flags, name))
            widget.setText(f"{name.upper()} {int(active)}")
            if widget.property("active") != active:
                widget.setProperty("active", active)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()

    def _may_replace_source(self) -> bool:
        if not self.editor.document().isModified():
            return True
        answer = QMessageBox.question(
            self, "Несохраненный исходник", "Заменить исходник и отбросить несохраненные изменения?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def load_example(self) -> None:
        if self.timer.isActive() or not self._may_replace_source():
            return
        self.current_path = None
        self.editor.setPlainText(example_source(str(self.example_box.currentData())))
        self.assemble_source()

    def open_source(self) -> None:
        if self.timer.isActive() or not self._may_replace_source():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Открыть программу", "", "Ассемблер (*.asm);;Все файлы (*)")
        if not filename:
            return
        try:
            path = Path(filename)
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            self._error(str(exc))
            return
        self.current_path = path
        self.editor.setPlainText(text)
        self.assemble_source()
        self.main_tabs.setCurrentIndex(0)
        self.source_tabs.setCurrentIndex(0)

    def save_source(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Сохранить программу", str(self.current_path or "program.asm"), "Ассемблер (*.asm)")
        if not filename:
            return
        try:
            Path(filename).write_text(self.editor.toPlainText(), encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self._error(str(exc))
            return
        self.current_path = Path(filename)
        self.editor.document().setModified(False)
        self._source_status()
        self.statusBar().showMessage(f"Сохранено: {filename}")

    def assemble_source(self) -> None:
        self.pause()
        source = self.editor.toPlainText()
        try:
            program = assemble(source)
        except EmulatorError as exc:
            self._error(str(exc))
            self._buttons()
            return
        self.program = program
        self.assembled_source = source
        self.listing.setRowCount(len(program.listing))
        for row, entry in enumerate(program.listing):
            for col, text in enumerate((f"0x{entry.address:04X}", f"0x{entry.word:08X}", re.split(r";|//", entry.source, maxsplit=1)[0].strip())):
                cell(self.listing, row, col, text)
        self.symbol_table.setRowCount(len(program.symbols))
        for row, (name, address) in enumerate(sorted(program.symbols.items(), key=lambda item: (item[1], item[0]))):
            cell(self.symbol_table, row, 0, name)
            cell(self.symbol_table, row, 1, f"0x{address:04X}")
            cell(self.symbol_table, row, 2, "Двойной щелчок: перейти в ОЗУ")
            self.symbol_table.item(row, 1).setData(Qt.ItemDataRole.UserRole, address)
        self.reset_cpu()
        text = f"Собрано: {len(program.listing)} инструкций. Точка входа 0x{program.entry:04X}."
        self.diagnostics.setPlainText(text)
        self.statusBar().showMessage(text)
        self._source_status()

    def reset_cpu(self) -> None:
        if self.program is None:
            return
        self.pause()
        self.cpu = CPU(self.program.image, self.program.entry)
        self.last_step = None
        self.last_description = None
        self.faulted = False
        self.error_label.clear()
        self.error_label.hide()
        self.trace.clear()
        self.records.clear()
        self.history_table.setRowCount(0)
        self.access_table.setRowCount(0)
        self._access_last_step = 0
        self.history_status.setText("История пуста")
        self.history_view.set_record(None)
        self.step_view.set_record(None)
        self.refresh()

    def step_once(self) -> None:
        if self.cpu is None or self.cpu.halted or self.faulted:
            return
        if self.editor.toPlainText() != self.assembled_source:
            self._error("Сначала собери измененный исходник.")
            return
        # Одна временная копия нужна для чтений и самомодифицирующегося кода.
        memory_before = self.cpu.memory.image()
        try:
            step = self.cpu.step()
        except EmulatorError as exc:
            self.faulted = True
            self.pause()
            self._error(str(exc))
            self.refresh()
            return
        self.last_step = step
        source = ""
        if self.program:
            source = next((row.source.strip() for row in self.program.listing
                           if row.address == step.address and row.word == step.after.ir), "")
        self.last_description = describe_step(step, memory_before, source)
        self._append_record(self.last_description)
        self.trace.appendPlainText(trace_line(step))
        self.error_label.hide()
        if self.cpu.halted:
            self.pause()
        self.refresh()

    def start_run(self) -> None:
        if self.cpu is None or self.cpu.halted or self.faulted:
            return
        if self.editor.toPlainText() != self.assembled_source:
            return
        self.step_view.stop_replay()
        self.run_budget = 100_000
        self.timer.start()
        self._buttons()

    def _tick(self) -> None:
        if self.run_budget <= 0:
            self.pause()
            self._error("Лимит 100000 команд исчерпан. CPU не остановлен HALT; доступно продолжение.")
            return
        self.step_once()
        self.run_budget -= 1

    def pause(self) -> None:
        self.timer.stop()
        self._buttons()

    def _error(self, message: str) -> None:
        self.error_label.setText(f"Ошибка: {message}")
        self.error_label.show()
        self.diagnostics.appendPlainText(f"Ошибка: {message}")
        self.statusBar().showMessage(message)

    def _append_record(self, record: StepDescription) -> None:
        self.records.append(record)
        if self.history_table.rowCount() >= HISTORY_LIMIT:
            self.history_table.removeRow(0)
        row = self.history_table.rowCount()
        self.history_table.insertRow(row)
        step = record.result
        for col, value in enumerate((str(step.after.steps), f"0x{step.address:04X}", step.instruction.assembly(),
                                     record.summary, f"0x{step.after.pc:04X}")):
            cell(self.history_table, row, col, value)
        self.history_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, record)
        first = self.records[0].result.after.steps
        self.history_status.setText(f"Сохранены шаги {first}–{step.after.steps} / предел {HISTORY_LIMIT}")
        # Не пересоздаем таблицы невидимых вкладок на каждом шаге.
        if self.main_tabs.currentIndex() == 3 and self.memory_tabs.currentIndex() == 2:
            self._refresh_accesses()

    def open_history(self, row: int | bool | None = None) -> None:
        if not self.records:
            return
        if row is None or isinstance(row, bool):
            row = self.history_table.currentRow()
        if row < 0:
            row = self.history_table.rowCount() - 1
        item = self.history_table.item(row, 0)
        if item is None:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        self.history_view.set_record(record)
        self.main_tabs.setCurrentIndex(4)
        self.history_tabs.setCurrentIndex(1)

    def export_history(self) -> None:
        if not self.records:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Сохранить историю", "trace.csv", "CSV (*.csv)")
        if not filename:
            return
        try:
            with Path(filename).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(("Шаг", "Адрес", "Команда", "Изменения", "PC после"))
                for record in self.records:
                    step = record.result
                    writer.writerow((step.after.steps, f"0x{step.address:04X}", step.instruction.assembly(),
                                     record.summary, f"0x{step.after.pc:04X}"))
        except (OSError, UnicodeError) as exc:
            self._error(str(exc))
            return
        self.statusBar().showMessage(f"История сохранена: {filename}")

    def go_to_address(self, address: int) -> None:
        self.main_tabs.setCurrentIndex(3)
        self.memory_tabs.setCurrentIndex(0)
        self.memory_page.setCurrentIndex(address // 256)
        self._refresh_memory()
        row = (address % 256) // 2
        self.memory_table.setCurrentCell(row, 0)
        self.memory_table.selectRow(row)
        item = self.memory_table.item(row, 0)
        if item:
            self.memory_table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    def show_result_memory(self) -> None:
        if self.program and "RESULT" in self.program.symbols:
            self.go_to_address(self.program.symbols["RESULT"])

    def _symbol_clicked(self, row: int, _col: int) -> None:
        item = self.symbol_table.item(row, 1)
        if item:
            self.go_to_address(int(item.data(Qt.ItemDataRole.UserRole)))

    def _refresh_memory(self, _index: int = 0) -> None:
        if not self.cpu or self.main_tabs.currentIndex() != 3 or self.memory_tabs.currentIndex() != 0:
            return
        base = int(self.memory_page.currentData() or 0)
        image = self.cpu.memory.image()
        changed = {address for address, old, new in self.last_step.memory_writes if old != new} if self.last_step else set()
        symbols: dict[int, list[str]] = {}
        if self.program:
            for name, address in self.program.symbols.items():
                symbols.setdefault(address, []).append(name)
        for row in range(128):
            address = base + 2 * row
            value = self.cpu.memory.read_word(address)
            values = (f"0x{address:04X}", f"{image[address]:02X} {image[address + 1]:02X}",
                      f"0x{value:04X}", str(signed(value)), ", ".join(symbols.get(address, [])))
            for col, text in enumerate(values):
                cell(self.memory_table, row, col, text, address in changed)

    def _refresh_accesses(self, _checked: bool = False) -> None:
        if self.main_tabs.currentIndex() != 3 or self.memory_tabs.currentIndex() != 2:
            return
        show_fetch = self.show_fetch.isChecked()
        if show_fetch != self._access_filter:
            self.access_table.setRowCount(0)
            self._access_last_step = 0
            self._access_filter = show_fetch
        if not self.records:
            self.access_table.setRowCount(0)
            self._access_last_step = 0
            return
        first = self.records[0].result.after.steps
        while self.access_table.rowCount() and int(self.access_table.item(0, 0).text()) < first:
            self.access_table.removeRow(0)
        # Добавляем только новые обращения, а не всю историю на каждом тике.
        self.access_table.setUpdatesEnabled(False)
        try:
            for record in self.records:
                number = record.result.after.steps
                if number <= self._access_last_step:
                    continue
                for access in record.accesses:
                    if not show_fetch and access.kind == "Выборка команды":
                        continue
                    row = self.access_table.rowCount()
                    self.access_table.insertRow(row)
                    width = access.width * 2
                    values = (str(number), access.kind, f"0x{access.address:04X}", str(access.width),
                              f"0x{access.value:0{width}X}", "—" if access.previous is None else f"0x{access.previous:04X}")
                    for col, text in enumerate(values):
                        cell(self.access_table, row, col, text)
            self._access_last_step = self.records[-1].result.after.steps
        finally:
            self.access_table.setUpdatesEnabled(True)

    def _refresh_registers(self) -> None:
        if not self.cpu or self.main_tabs.currentIndex() != 2:
            return
        for row, value in enumerate(self.cpu.registers):
            changed = bool(self.last_step and value != self.last_step.before.registers[row])
            for col, text in enumerate((f"R{row}", f"0x{value:04X}", str(signed(value)), str(value))):
                cell(self.register_table, row, col, text, changed)
        cpu = self.cpu
        rows = [("PC", f"0x{cpu.pc:04X}", "Адрес следующей инструкции"),
                ("IR", f"0x{cpu.ir:08X}", "Последняя успешно выполненная инструкция"),
                ("HALTED", str(int(cpu.halted)), "Остановка процессора"),
                ("Шаги", str(cpu.steps), "Счетчик отладчика, не аппаратный регистр")]
        rows += [(name.upper(), str(int(getattr(cpu.flags, name))), meaning) for name, meaning in
                 (("zf", "Флаг нуля"), ("sf", "Флаг знака"), ("cf", "Флаг переноса / заема"), ("of", "Знаковое переполнение"))]
        self.special_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, text in enumerate(values):
                cell(self.special_table, row, col, text)

    def refresh(self) -> None:
        if self.cpu is None:
            return
        cpu = self.cpu
        self._refresh_registers()
        self._refresh_memory()
        self.step_view.set_record(self.last_description)
        if self.last_step:
            i = self.last_step.instruction
            self.instruction_text.setPlainText(
                f"Последняя успешно выполненная инструкция\n\nАдрес: 0x{self.last_step.address:04X}\n"
                f"ASM: {i.assembly()}\nIR: 0x{cpu.ir:08X}\n\n"
                f"opcode [31:24]   {int(i.opcode):08b}   0x{int(i.opcode):02X}\n"
                f"reg    [23:20]   {i.register:04b}       R{i.register}\n"
                f"mode   [19:18]   {int(i.mode):02b}         {i.mode.name}\n"
                f"reserve[17:16]   00\noperand[15:0]   {i.operand:016b}   0x{i.operand:04X}\n\n"
                f"Флаги после: {flags_text(cpu.flags)}")
        else:
            self.instruction_text.setPlainText("IR=0x00000000 после сброса. Ни одна команда еще не исполнена.")
        upcoming_word = None
        if cpu.halted:
            upcoming = "не выполняется: достигнут HALT"
        elif self.faulted:
            upcoming = "исполнение остановлено из-за ошибки CPU"
        else:
            try:
                upcoming_word = cpu.memory.read_instruction(cpu.pc)
                upcoming = decode(upcoming_word).assembly()
            except EmulatorError as exc:
                upcoming = f"ошибка чтения: {exc}"
        text = f"По PC следующая: {upcoming}\n\nR2:R1:R0 (signed 48): {join_words(cpu.registers[:3])}"
        if self.program and "RESULT" in self.program.symbols:
            address = self.program.symbols["RESULT"]
            try:
                parts = [cpu.memory.read_word(address + 2 * n) for n in range(3)]
                text += f"\nОЗУ RESULT (signed 48): {join_words(parts)}\nСлова low → high: " + " ".join(f"{x:04X}" for x in parts)
            except EmulatorError:
                text += "\nRESULT: для трех слов не хватает ОЗУ"
            text += "\n\nДля встроенных задач: R15=0 — успех; R15=1 — ошибка заголовков."
        self.result_label.setText(text)
        self.listing.clearSelection()
        selections = []
        if self.program and not cpu.halted and not self.faulted and self.editor.toPlainText() == self.assembled_source:
            for index, row in enumerate(self.program.listing):
                if row.address == cpu.pc and row.word == upcoming_word:
                    self.listing.selectRow(index)
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = QTextCursor(self.editor.document().findBlockByNumber(row.line - 1))
                    selection.format.setBackground(QColor(NEXT_BG))
                    selection.format.setForeground(QColor(NEXT_INK))
                    selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                    selections.append(selection)
                    break
        self.editor.setExtraSelections(selections)
        self._buttons()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._may_replace_source():
            self.timer.stop()
            self.step_view.stop_replay()
            self.history_view.stop_replay()
            event.accept()
        else:
            event.ignore()


def launch() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window = MainWindow()
    screen = app.primaryScreen()
    if screen:
        available = screen.availableGeometry()
        window.resize(min(1200, max(640, available.width() - 40)), min(830, max(480, available.height() - 60)))
    window.show()
    return app.exec()
