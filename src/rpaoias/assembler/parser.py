"""Синтаксический анализ строк: метка, мнемоника и группы токенов операндов.

Методичка, 4.4: для простого ассемблера сложное AST не обязательно.
Здесь промежуточное представление – ParsedLine. Семантика ISA проверяется
отдельно, поэтому парсер не содержит условных веток для каждой команды.
"""

from dataclasses import dataclass

from rpaoias.assembler.lexer import Token, tokenize
from rpaoias.errors import AssemblyError


@dataclass(frozen=True, slots=True)
class ParsedLine:
    number: int
    source: str
    label: str | None
    operation: str | None
    operands: tuple[tuple[Token, ...], ...]


def parse(source: str) -> tuple[ParsedLine, ...]:
    """Комментарии не становятся инструкциями, но исходные строки сохраняются."""
    result: list[ParsedLine] = []
    for number, original in enumerate(source.splitlines(), start=1):
        tokens = list(tokenize(original, number))
        if not tokens:
            continue
        label = None
        if len(tokens) >= 2 and tokens[1].text == ":":
            if tokens[0].kind != "IDENT" or tokens[0].text.startswith("."):
                raise AssemblyError("Недопустимое имя метки", number, tokens[0].column)
            label = tokens[0].text.upper()
            tokens = tokens[2:]
        if not tokens:
            result.append(ParsedLine(number, original, label, None, ()))
            continue
        first = tokens.pop(0)
        if first.kind != "IDENT":
            raise AssemblyError("Ожидалась мнемоника или директива", number, first.column)
        groups: list[tuple[Token, ...]] = []
        current: list[Token] = []
        depth = 0
        for token in tokens:
            if token.text == "[":
                depth += 1
                if depth > 1:
                    raise AssemblyError("Вложенные скобки не поддерживаются", number, token.column)
            elif token.text == "]":
                depth -= 1
                if depth < 0:
                    raise AssemblyError("Лишняя закрывающая скобка", number, token.column)
            if token.text == "," and depth == 0:
                if not current:
                    raise AssemblyError("Пустой операнд перед запятой", number, token.column)
                groups.append(tuple(current))
                current = []
            else:
                current.append(token)
        if depth:
            raise AssemblyError("Не закрыта квадратная скобка", number, first.column)
        if tokens and not current:
            raise AssemblyError("После запятой отсутствует операнд", number, tokens[-1].column)
        if current:
            groups.append(tuple(current))
        result.append(ParsedLine(number, original, label, first.text.upper(), tuple(groups)))
    return tuple(result)
