"""Лексический анализ: из символов в токены с координатами.

Методичка, 4.4, стр. 49–50: лексер узнает отдельные элементы, но еще
не решает, допустима ли вся команда. Квадратная скобка – токен;
проверка, что внутри указан корректный адрес, относится к следующим этапам.

eval() здесь нет: текст ассемблера не должен становиться Python-кодом.
"""

import re
from dataclasses import dataclass

from rpaoias.errors import AssemblyError


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    line: int
    column: int


# Порядок альтернатив важен: 0x10 нужно узнать целиком, а не как 0 и x10.
TOKEN = re.compile(
    r"(?P<SPACE>[ \t]+)|(?P<COMMENT>;.*|//.*)|"
    r"(?P<NUMBER>0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)|"
    r"(?P<IDENT>\.?[A-Za-z_][A-Za-z_0-9]*)|"
    r"(?P<PUNCT>[\[\],:+\-])"
)


def tokenize(line: str, line_number: int) -> tuple[Token, ...]:
    """Распознаем всю строку: незнакомый символ нельзя молча пропустить."""
    tokens: list[Token] = []
    offset = 0
    while offset < len(line):
        match = TOKEN.match(line, offset)
        if match is None:
            raise AssemblyError(f"Недопустимый символ {line[offset]!r}", line_number, offset + 1)
        kind = match.lastgroup
        if kind == "COMMENT":
            break
        if kind != "SPACE":
            tokens.append(Token(str(kind), match.group(), line_number, offset + 1))
        offset = match.end()
    return tuple(tokens)
