"""Двухпроходный ассемблер: сначала адреса, затем машинные инструкции.

Методичка, стр. 54, описывает таблицу меток и неразрешенные ссылки.
Мы выбираем другой конкретный алгоритм: первый проход узнает адреса ВСЕХ
меток, второй подставляет их значения. Поэтому JMP вперед не отличается
по сложности от JMP назад. Это наше проектное решение.

.org и .word – директивы сборщика, а не команды процессора. В частности,
метка не занимает четыре байта и не сдвигает PC сама по себе.
"""

import re
from dataclasses import dataclass

from rpaoias.assembler.lexer import Token
from rpaoias.assembler.parser import ParsedLine, parse
from rpaoias.cpu.word import INSTRUCTION_BYTES, MEMORY_BYTES, WORD_MASK
from rpaoias.errors import AssemblyError, CPUFault
from rpaoias.isa.codec import encode
from rpaoias.isa.instruction import JUMPS, NO_OPERANDS, Instruction, Mode, Opcode

REGISTER = re.compile(r"R([0-9]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ListingEntry:
    address: int
    line: int
    source: str
    word: int


@dataclass(frozen=True, slots=True)
class Program:
    """Образ единой памяти и отладочные метаданные; CPU получает только image/entry."""

    image: bytes
    entry: int
    symbols: dict[str, int]
    listing: tuple[ListingEntry, ...]


def _error(message: str, tokens: tuple[Token, ...]) -> AssemblyError:
    return AssemblyError(message, tokens[0].line, tokens[0].column)


def _expression(tokens: tuple[Token, ...], symbols: dict[str, int]) -> int:
    """Небольшая грамматика: необязательный знак, затем числа/метки через +/-.

    Поддерживаем result+2 и -32768, но не вызываем eval и не имитируем
    полноценный язык выражений. Неподдерживаемую запись отвергаем явно.
    """
    if not tokens:
        raise AssemblyError("Пустое выражение")
    total = 0
    index = 0
    sign = 1
    if tokens[0].text in ("+", "-"):
        sign = -1 if tokens[0].text == "-" else 1
        index += 1
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "NUMBER":
            base = 16 if token.text.lower().startswith("0x") else (
                2 if token.text.lower().startswith("0b") else 10)
            try:
                value = int(token.text, base)
            except ValueError as exc:
                raise AssemblyError("Числовой литерал слишком длинный или некорректный",
                                    token.line, token.column) from exc
        elif token.kind == "IDENT" and not token.text.startswith("."):
            name = token.text.upper()
            if name not in symbols:
                raise AssemblyError(f"Неизвестная метка {token.text}", token.line, token.column)
            value = symbols[name]
        else:
            raise AssemblyError("Ожидалось число или имя метки", token.line, token.column)
        total += sign * value
        index += 1
        if index == len(tokens):
            return total
        operator = tokens[index]
        if operator.text not in ("+", "-"):
            raise AssemblyError("Между частями выражения нужен + или -", operator.line, operator.column)
        sign = -1 if operator.text == "-" else 1
        index += 1
    raise _error("Выражение заканчивается знаком без числа", tokens)


def _register(tokens: tuple[Token, ...]) -> int | None:
    if len(tokens) != 1:
        return None
    match = REGISTER.fullmatch(tokens[0].text)
    if match is None:
        return None
    number = int(match.group(1))
    if number >= 16:
        raise _error("Доступны только регистры R0..R15", tokens)
    return number


def _operand(tokens: tuple[Token, ...], symbols: dict[str, int]) -> tuple[Mode, int]:
    """Квадратные скобки меняют смысл: адрес, а не значение по этому адресу."""
    register = _register(tokens)
    if register is not None:
        return Mode.REGISTER, register
    if tokens[0].text == "[":
        if tokens[-1].text != "]" or len(tokens) <= 2:
            raise _error("Ожидался адрес внутри [...]", tokens)
        inside = tokens[1:-1]
        register = _register(inside)
        if register is not None:
            return Mode.INDIRECT, register
        return Mode.DIRECT, _expression(inside, symbols)
    value = _expression(tokens, symbols)
    if not -32768 <= value <= WORD_MASK:
        raise _error("Литерал не помещается в 16 бит (-32768..65535)", tokens)
    # Отрицательная запись разрешена в исходнике, но поле машины хранит биты.
    return Mode.IMMEDIATE, value & WORD_MASK


def _count(line: ParsedLine, expected: int) -> None:
    if len(line.operands) != expected:
        raise AssemblyError(f"{line.operation}: нужно операндов {expected}, получено {len(line.operands)}",
                            line.number)


def _instruction(line: ParsedLine, symbols: dict[str, int]) -> Instruction:
    if line.operation == "STORE":
        raise AssemblyError("Используй MOV [адрес], Rn; STORE – внутреннее имя opcode", line.number)
    try:
        opcode = Opcode[str(line.operation)]
    except KeyError as exc:
        raise AssemblyError(f"Неизвестная команда {line.operation}", line.number) from exc
    if opcode in NO_OPERANDS:
        _count(line, 0)
        return Instruction(opcode)
    if opcode in JUMPS:
        _count(line, 1)
        # Адрес не маскируем: JMP -4 не должен превращаться в 65532.
        return Instruction(opcode, 0, Mode.IMMEDIATE, _expression(line.operands[0], symbols))
    _count(line, 2)
    destination_mode, destination = _operand(line.operands[0], symbols)
    source_mode, source = _operand(line.operands[1], symbols)
    if opcode == Opcode.MOV and destination_mode in (Mode.DIRECT, Mode.INDIRECT):
        if source_mode != Mode.REGISTER:
            raise AssemblyError("Для MOV в память источником должен быть регистр", line.number)
        return Instruction(Opcode.STORE, source, destination_mode, destination)
    if destination_mode != Mode.REGISTER:
        raise AssemblyError("Первый операнд этой команды должен быть регистром", line.number)
    return Instruction(opcode, destination, source_mode, source)


def assemble(source: str) -> Program:
    """Полная трансляция; при ошибке частично собранный образ наружу не выходит."""
    lines = parse(source)
    symbols: dict[str, int] = {}
    located: list[tuple[int, ParsedLine]] = []
    entry_line: ParsedLine | None = None
    address = 0

    # ПРОХОД 1: размер каждого оператора известен без адресов будущих меток.
    for line in lines:
        if line.label:
            if line.label in symbols:
                raise AssemblyError(f"Повторное объявление метки {line.label}", line.number)
            if REGISTER.fullmatch(line.label):
                raise AssemblyError("Имя регистра нельзя использовать как метку", line.number)
            if line.operation == ".ORG":
                raise AssemblyError("Размести метку после .org на отдельной строке", line.number)
            symbols[line.label] = address
        if line.operation is None:
            continue
        if line.operation == ".ORG":
            _count(line, 1)
            # .org не зависит от меток, чтобы не получить циклические адреса.
            if any(token.kind == "IDENT" for token in line.operands[0]):
                raise AssemblyError(".org принимает только числовое выражение", line.number)
            address = _expression(line.operands[0], {})
            if not 0 <= address < MEMORY_BYTES:
                raise AssemblyError(".org выходит за память 0..4095", line.number)
            continue
        if line.operation == ".ENTRY":
            _count(line, 1)
            if entry_line is not None:
                raise AssemblyError("Директива .entry может встречаться только один раз", line.number)
            entry_line = line
            continue
        if line.operation.startswith(".") and line.operation != ".WORD":
            raise AssemblyError(f"Неизвестная директива {line.operation}", line.number)
        if line.operation == ".WORD":
            if not line.operands:
                raise AssemblyError(".word требует хотя бы одно значение", line.number)
            width, alignment = 2 * len(line.operands), 2
        else:
            width, alignment = INSTRUCTION_BYTES, INSTRUCTION_BYTES
        if address % alignment or address + width > MEMORY_BYTES:
            raise AssemblyError("Размещение выходит за ОЗУ или нарушает выравнивание", line.number)
        located.append((address, line))
        address += width

    # ПРОХОД 2: у каждой метки уже есть адрес. В один образ пишутся и код, и данные.
    image = bytearray(MEMORY_BYTES)
    occupied: set[int] = set()
    listing: list[ListingEntry] = []
    for address, line in located:
        if line.operation == ".WORD":
            data = bytearray()
            for expression in line.operands:
                value = _expression(expression, symbols)
                if not -32768 <= value <= WORD_MASK:
                    raise _error("Значение .word не помещается в 16 бит", expression)
                data.extend((value & WORD_MASK).to_bytes(2, "little"))
        else:
            try:
                instruction = _instruction(line, symbols)
                word = encode(instruction)
            except CPUFault as exc:
                raise AssemblyError(str(exc), line.number) from exc
            data = bytearray(word.to_bytes(INSTRUCTION_BYTES, "little"))
            listing.append(ListingEntry(address, line.number, line.source, word))
        addresses = set(range(address, address + len(data)))
        if occupied & addresses:
            raise AssemblyError("Области кода/данных перекрываются; проверь .org", line.number)
        occupied.update(addresses)
        image[address:address + len(data)] = data
    if not listing:
        raise AssemblyError("Программа не содержит машинных инструкций")
    entry = _expression(entry_line.operands[0], symbols) if entry_line else 0
    if entry not in {row.address for row in listing}:
        raise AssemblyError("Точка входа должна указывать на собранную инструкцию",
                            entry_line.number if entry_line else 1)
    return Program(bytes(image), entry, symbols, tuple(listing))
