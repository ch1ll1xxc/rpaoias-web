"""Машинное кодирование проверяем независимо от ассемблерных строк."""

import pytest

from rpaoias.errors import CPUFault
from rpaoias.isa.codec import decode, encode
from rpaoias.isa.instruction import ARITHMETIC, JUMPS, Instruction, Mode, Opcode


@pytest.mark.parametrize("mode,operand", [(Mode.REGISTER, 12), (Mode.IMMEDIATE, 65535),
                                           (Mode.DIRECT, 1024), (Mode.INDIRECT, 3)])
@pytest.mark.parametrize("register", range(16))
def test_roundtrip_preserves_every_mov_field(mode, operand, register):
    instruction = Instruction(Opcode.MOV, register, mode, operand)
    assert decode(encode(instruction)) == instruction


@pytest.mark.parametrize("opcode", sorted(ARITHMETIC))
@pytest.mark.parametrize("mode,operand", [(Mode.REGISTER, 7), (Mode.IMMEDIATE, 3)])
def test_arithmetic_roundtrip(opcode, mode, operand):
    instruction = Instruction(opcode, 6, mode, operand)
    assert decode(encode(instruction)) == instruction


@pytest.mark.parametrize("opcode", sorted(JUMPS))
def test_jump_roundtrip(opcode):
    instruction = Instruction(opcode, 0, Mode.IMMEDIATE, 4)
    assert decode(encode(instruction)) == instruction


def test_known_layout_is_not_just_self_consistent():
    """Проверяем конкретную ручную кодировку, не только encode(decode(x))."""
    instruction = Instruction(Opcode.MOV, 2, Mode.IMMEDIATE, 12)
    assert encode(instruction) == 0x0124000C
    assert decode(0x0124000C).assembly() == "MOV R2, 0x000C"
    assert encode(Instruction(Opcode.HALT)) == 0xFF000000


@pytest.mark.parametrize("instruction", [
    Instruction(Opcode.ADD, 0, Mode.DIRECT, 1024),
    Instruction(Opcode.MUL, 1, Mode.REGISTER, 2),
    Instruction(Opcode.MOV, 16, Mode.IMMEDIATE, 1),
    Instruction(Opcode.MOV, 0, Mode.REGISTER, 16),
    Instruction(Opcode.MOV, 0, Mode.INDIRECT, 16),
    Instruction(Opcode.MOV, 0, Mode.DIRECT, 4096),
    Instruction(Opcode.MOV, 0, Mode.DIRECT, 3),
    Instruction(Opcode.MOV, 0, Mode.IMMEDIATE, -1),
    Instruction(Opcode.MOV, 0, Mode.IMMEDIATE, 65536),
    Instruction(Opcode.HALT, 1),
    Instruction(Opcode.NOP, 0, Mode.IMMEDIATE, 0),
    Instruction(Opcode.JMP, 0, Mode.IMMEDIATE, 2),
    Instruction(Opcode.JMP, 0, Mode.IMMEDIATE, 4096),
    Instruction(Opcode.STORE, 0, Mode.IMMEDIATE, 1),
])
def test_invalid_fields_are_rejected_not_truncated(instruction):
    with pytest.raises(CPUFault):
        encode(instruction)


@pytest.mark.parametrize("word", [-1, 0x100000000, 0xAB000000, 0x01010000])
def test_invalid_machine_words_fault(word):
    with pytest.raises(CPUFault):
        decode(word)
