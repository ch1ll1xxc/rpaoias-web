"""Система команд: договор между ассемблером, декодером и CPU.

Методичка: разделы 2.1–2.3 и 4.1. Номера opcode, разрядности полей,
правила MUL и ограничение сочетаний операндов выбраны в нашем проекте.
Это не кодировка NASM, x86 или RISC-V.

Двухадресность означает, что арифметика явно называет два операнда;
первый также является приемником результата. Она не означает, что каждая
инструкция обязана иметь два текстовых аргумента: HALT обходится без них.
"""

from dataclasses import dataclass
from enum import IntEnum

from rpaoias.cpu.word import MEMORY_BYTES, REGISTER_COUNT, WORD_MASK
from rpaoias.errors import CPUFault


class Mode(IntEnum):
    """Два бита задают интерпретацию 16-битного поля operand."""

    REGISTER = 0       # operand – номер регистра, а не его значение.
    IMMEDIATE = 1      # operand – само число.
    DIRECT = 2         # operand – байтовый адрес слова в ОЗУ.
    INDIRECT = 3       # operand – номер регистра, в котором находится адрес.


class Opcode(IntEnum):
    NOP = 0x00
    MOV = 0x01         # Чтение в регистр: из регистра, литерала или памяти.
    STORE = 0x02       # Запись регистра в память; в ассемблере тоже MOV.
    ADD = 0x10
    ADC = 0x11
    SUB = 0x12
    MUL = 0x13
    CMP = 0x14
    SAR = 0x15
    JMP = 0x20
    JZ = 0x21
    JNZ = 0x22
    JC = 0x23
    JNC = 0x24
    JO = 0x25
    JNO = 0x26
    HALT = 0xFF


ARITHMETIC = frozenset({Opcode.ADD, Opcode.ADC, Opcode.SUB, Opcode.MUL,
                        Opcode.CMP, Opcode.SAR})
JUMPS = frozenset({Opcode.JMP, Opcode.JZ, Opcode.JNZ, Opcode.JC,
                   Opcode.JNC, Opcode.JO, Opcode.JNO})
NO_OPERANDS = frozenset({Opcode.NOP, Opcode.HALT})


@dataclass(frozen=True, slots=True)
class Instruction:
    """Декодированные поля, а не отдельное хранилище исполняемой программы."""

    opcode: Opcode
    register: int = 0
    mode: Mode = Mode.REGISTER
    operand: int = 0

    def validate(self) -> None:
        """Одна проверка используется и перед кодированием, и после декодирования.

        Недопустимые сочетания нельзя молча обрезать маской: так R16 мог бы
        незаметно превратиться в R0. Маски допустимы для результата АЛУ,
        но не вместо проверки формата машинной инструкции.
        """
        if not isinstance(self.opcode, Opcode) or not isinstance(self.mode, Mode):
            raise CPUFault("Неизвестный opcode или режим адресации")
        if not 0 <= self.register < REGISTER_COUNT or not 0 <= self.operand <= WORD_MASK:
            raise CPUFault("Поле инструкции выходит за допустимый диапазон")
        if self.opcode in NO_OPERANDS:
            if self.register or self.operand or self.mode != Mode.REGISTER:
                raise CPUFault("У NOP/HALT все неиспользуемые поля должны быть нулевыми")
            return
        if self.opcode in JUMPS:
            if self.register != 0 or self.mode != Mode.IMMEDIATE:
                raise CPUFault("Переход кодируется абсолютным адресом и register=0")
            if self.operand % 4 or not 0 <= self.operand <= MEMORY_BYTES - 4:
                raise CPUFault("Адрес перехода должен указывать на выровненную инструкцию в ОЗУ")
            return
        if self.mode in (Mode.REGISTER, Mode.INDIRECT) and self.operand >= REGISTER_COUNT:
            raise CPUFault("В поле операнда должен быть номер R0..R15")
        if self.mode == Mode.DIRECT:
            if self.operand % 2 or self.operand > MEMORY_BYTES - 2:
                raise CPUFault("Прямой адрес должен указывать на выровненное слово в ОЗУ")
        if self.opcode == Opcode.STORE and self.mode not in (Mode.DIRECT, Mode.INDIRECT):
            raise CPUFault("Запись в ОЗУ требует прямой или косвенно-регистровой адресации")
        if self.opcode in ARITHMETIC and self.mode not in (Mode.REGISTER, Mode.IMMEDIATE):
            raise CPUFault("Арифметика работает с регистрами/литералами, но не напрямую с ОЗУ")
        if self.opcode == Opcode.MUL and self.register % 2:
            raise CPUFault("MUL требует четный приемник: R0, R2, ..., R14")
        if self.opcode == Opcode.SAR and self.mode == Mode.IMMEDIATE and self.operand > 15:
            raise CPUFault("SAR допускает число сдвигов от 0 до 15")

    def assembly(self) -> str:
        """Обратное текстовое представление. Имена меток в машинном коде утрачены."""
        if self.opcode in NO_OPERANDS:
            return self.opcode.name
        if self.opcode in JUMPS:
            return f"{self.opcode.name} 0x{self.operand:04X}"
        other = {
            Mode.REGISTER: f"R{self.operand}",
            Mode.IMMEDIATE: f"0x{self.operand:04X}",
            Mode.DIRECT: f"[0x{self.operand:04X}]",
            Mode.INDIRECT: f"[R{self.operand}]",
        }[self.mode]
        if self.opcode == Opcode.STORE:
            return f"MOV {other}, R{self.register}"
        return f"{self.opcode.name} R{self.register}, {other}"
