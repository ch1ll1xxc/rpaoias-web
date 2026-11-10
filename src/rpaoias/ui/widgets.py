"""Общие виджеты и просмотр сохраненного шага. Без доступа к CPU."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from rpaoias.ui.step_description import StepDescription
from rpaoias.ui.theme import CHANGED_BG, CHANGED_INK, fixed_font


def label(text: str = "", role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setProperty("role", role)
    return widget


def page() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    return widget, layout


def table(headers: list[str], rows: int = 0, widths: list[int] | None = None) -> QTableWidget:
    widget = QTableWidget(rows, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.setWordWrap(False)
    widget.setFont(fixed_font())
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(29)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    for n, width in enumerate(widths or []):
        widget.setColumnWidth(n, width)
    return widget


def cell(widget: QTableWidget, row: int, col: int, text: str, changed: bool = False) -> None:
    item = widget.item(row, col)
    if item is None:
        item = QTableWidgetItem()
        widget.setItem(row, col, item)
    if item.text() != text:
        item.setText(text)
    item.setToolTip(text + ("\nИзменилось за последний шаг" if changed else ""))
    item.setBackground(QBrush(QColor(CHANGED_BG)) if changed else QBrush())
    item.setForeground(QBrush(QColor(CHANGED_INK)) if changed else QBrush())
    font = widget.font()
    font.setBold(changed)
    item.setFont(font)


def horizontal_scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setWidget(widget)
    area.setFixedHeight(widget.sizeHint().height() + 15)
    return area


class StepView(QWidget):
    """Переключение фаз и повтор показа не вызывают CPU.step()."""

    def __init__(self, historical: bool = False) -> None:
        super().__init__()
        self.record: StepDescription | None = None
        self.historical = historical
        self.phase_index = 2
        self.timer = QTimer(self)
        self.timer.setInterval(850)
        self.timer.timeout.connect(self._advance)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.caption = label("Ни одна команда еще не выполнена", "muted")
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        self.command = label("Нажми «Шаг»", "heading")
        self.command.setWordWrap(True)
        self.command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.command)
        self.source_label = label("", "muted")
        self.source_label.setWordWrap(True)
        self.source_label.hide()
        layout.addWidget(self.source_label)
        phase_box = QWidget()
        phase_row = QHBoxLayout(phase_box)
        phase_row.setContentsMargins(0, 0, 0, 0)
        phase_row.setSpacing(7)
        self.phase_group = QButtonGroup(self)
        self.phase_buttons = []
        for n, text in enumerate(("1. Выборка", "2. Разбор", "3. Операция", "4. Запись")):
            button = QPushButton(text)
            button.setCheckable(True)
            self.phase_group.addButton(button, n)
            self.phase_buttons.append(button)
            phase_row.addWidget(button)
            if n < 3:
                phase_row.addWidget(label("→", "muted"))
        phase_row.addStretch()
        self.phase_group.idClicked.connect(self._select_phase)
        layout.addWidget(horizontal_scroll(phase_box))

        self.flow = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.flow.setSpacing(9)
        self.flow_labels = []
        self.arrows = []
        for n, heading in enumerate(("ИСТОЧНИК", "ДЕЙСТВИЕ", "РЕЗУЛЬТАТ")):
            frame = QFrame()
            frame.setProperty("role", "flow")
            frame.setProperty("center", n == 1)
            frame.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(14, 12, 14, 12)
            frame_layout.addWidget(label(heading, "section"))
            text = label("—")
            text.setFont(fixed_font())
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            frame_layout.addWidget(text, 1)
            self.flow_labels.append(text)
            self.flow.addWidget(frame, 1)
            if n < 2:
                arrow = label("→", "muted")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.arrows.append(arrow)
                self.flow.addWidget(arrow)
        layout.addLayout(self.flow)
        self.detail = label("Здесь появится разбор реально выполненной команды.", "muted")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail)
        row = QHBoxLayout()
        row.addWidget(label("Изменения за всю команду", "section"))
        row.addStretch()
        self.replay_button = QPushButton("Показать разбор")
        self.replay_button.setToolTip("Последовательно показать пояснения четырех этапов. CPU не изменяется.")
        self.replay_button.clicked.connect(self.replay)
        row.addWidget(self.replay_button)
        layout.addLayout(row)
        self.changes = table(["Объект", "До", "После", "Пояснение"], widths=[150, 130, 130, 310])
        self.changes.setMinimumHeight(95)
        layout.addWidget(self.changes, 1)
        note = label("Разбор завершенной команды. Этапы показа не являются аппаратными тактами.", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.set_record(None)

    def set_record(self, record: StepDescription | None) -> None:
        if record is not None and record is self.record:
            return
        self.timer.stop()
        self.replay_button.setText("Показать разбор")
        self.record = record
        self.replay_button.setEnabled(record is not None)
        for button in self.phase_buttons:
            button.setEnabled(record is not None)
        if record is None:
            self.caption.setText("Ни одна команда еще не выполнена")
            self.command.setText("Нажми «Шаг»")
            self.source_label.hide()
            for text in self.flow_labels:
                text.setText("—")
            self.detail.setText("Здесь появится разбор реально выполненной команды.")
            self.changes.setRowCount(0)
            return
        step = record.result
        prefix = "Архивный шаг" if self.historical else "Последний завершенный шаг"
        suffix = ". Просмотр не меняет текущее состояние CPU." if self.historical else ""
        self.caption.setText(f"{prefix} {step.after.steps} / адрес 0x{step.address:04X}{suffix}")
        self.command.setText(step.instruction.assembly())
        self.source_label.setText("Исходник: " + record.source)
        self.source_label.setVisible(bool(record.source))
        self.changes.setRowCount(len(record.changes))
        for row, change in enumerate(record.changes):
            for col, text in enumerate((change.name, change.before, change.after, change.note)):
                cell(self.changes, row, col, text, col == 2)
        self._select_phase(2)

    def _select_phase(self, index: int) -> None:
        if not self.record:
            return
        self.phase_index = index
        self.phase_buttons[index].setChecked(True)
        phase = self.record.phases[index]
        for widget, text in zip(self.flow_labels, (phase.source, phase.operation, phase.target), strict=True):
            widget.setText(text)
        self.detail.setText(phase.detail)

    def replay(self) -> None:
        if not self.record:
            return
        if self.timer.isActive():
            self.stop_replay()
            return
        self._select_phase(0)
        self.replay_button.setText("Остановить показ")
        self.timer.start()

    def stop_replay(self) -> None:
        self.timer.stop()
        self.replay_button.setText("Показать разбор")

    def _advance(self) -> None:
        if self.phase_index >= 3:
            self.stop_replay()
        else:
            self._select_phase(self.phase_index + 1)
            if self.phase_index == 3:
                self.stop_replay()

    def resizeEvent(self, event) -> None:  # noqa: N802
        narrow = self.width() < 730
        self.flow.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        for arrow in self.arrows:
            arrow.setText("↓" if narrow else "→")
        super().resizeEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.stop_replay()
        super().hideEvent(event)
