"""Подсветка исходника. Допустимость инструкций проверяет ассемблер."""
import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from rpaoias.isa.instruction import Opcode


class AssemblyHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        names = "|".join(op.name for op in Opcode if op != Opcode.STORE)
        self.rules = []
        for pattern, color, bold in (
            (rf"\b(?:{names})\b", "#95375F", True),
            (r"\bR(?:1[0-5]|[0-9])\b", "#725089", False),
            (r"(?<!\w)[+-]?(?:0x[0-9a-f]+|0b[01]+|[0-9]+)\b", "#855E28", False),
            (r"\.(?:org|entry|word)\b", "#366F70", True),
            (r"^\s*[A-Za-z_][A-Za-z_0-9]*(?=:)", "#366F70", True),
            (r"(?:;|//).*$", "#897080", False),
        ):
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            if bold:
                style.setFontWeight(QFont.Weight.Bold)
            self.rules.append((re.compile(pattern, re.IGNORECASE), style))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, style in self.rules:
            for match in pattern.finditer(text):
                # Qt считает позиции в единицах UTF-16, Python – в кодовых точках.
                start = len(text[:match.start()].encode("utf-16-le")) // 2
                count = len(match.group().encode("utf-16-le")) // 2
                self.setFormat(start, count, style)
