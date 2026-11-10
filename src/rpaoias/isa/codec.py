"""Машинная инструкция всегда занимает 32 бита / 4 байта.

  31             24 23      20 19    18 17    16 15                 0
 +----------------+----------+--------+--------+--------------------+
 | opcode: 8      | reg: 4   | mode:2 | zero:2 | operand: 16        |
 +----------------+----------+--------+--------+--------------------+

Методичка, 4.3: выделение полей через сдвиг и маску. Здесь формат свой.
Поля не обязаны быть одинакового смысла: у STORE reg – источник, у ADD –
первый операнд/приемник. Число operand трактуется согласно mode.

Единый 32-битный формат помещается потому, что хотя бы один операнд MOV
является регистром. MOV [address], [address] сознательно не поддерживается.
"""

from rpaoias.errors import CPUFault
from rpaoias.isa.instruction import Instruction, Mode, Opcode


def encode(instruction: Instruction) -> int:
    """Сдвигаем поля на их места и объединяем непересекающиеся биты через OR."""
    instruction.validate()
    return (int(instruction.opcode) << 24
            | instruction.register << 20
            | int(instruction.mode) << 18
            | instruction.operand)


def decode(word: int) -> Instruction:
    """Обратная операция: сдвиг убирает младшие поля, маска отсекает старшие."""
    if not 0 <= word <= 0xFFFFFFFF:
        raise CPUFault("Машинная инструкция должна содержать ровно до 32 значащих бит")
    # Резервные биты не игнорируем: случайная порча кода не должна
    # незаметно трактоваться как корректная каноническая инструкция.
    if word & 0x00030000:
        raise CPUFault("Ненулевые резервные биты 17..16")
    try:
        instruction = Instruction(
            opcode=Opcode((word >> 24) & 0xFF),
            register=(word >> 20) & 0xF,
            mode=Mode((word >> 18) & 0x3),
            operand=word & 0xFFFF,
        )
    except ValueError as exc:
        raise CPUFault(f"Неизвестный opcode: 0x{(word >> 24) & 0xFF:02X}") from exc
    instruction.validate()
    return instruction
