"""Проверяем поведение настоящего fetch/decode/execute, а не только АЛУ."""

import pytest

from rpaoias.assembler.assembler import assemble
from rpaoias.cpu.memory import Memory
from rpaoias.cpu.processor import CPU
from rpaoias.errors import CPUFault, ExecutionLimit


def machine(source: str) -> CPU:
    program = assemble(source)
    return CPU(program.image, program.entry)


def test_all_four_addressing_modes_and_both_stores():
    cpu = machine("MOV R0,7\nMOV R1,R0\nMOV R2,[data]\nMOV R3,data\n"
                  "MOV R4,[R3]\nMOV [R3],R0\nMOV [data+2],R4\nHALT\n"
                  ".org 256\ndata: .word 99,0")
    cpu.run()
    assert cpu.registers[:5] == [7, 7, 99, 256, 99]
    assert cpu.memory.read_word(256) == 7
    assert cpu.memory.read_word(258) == 99


def test_cmp_updates_flags_without_replacing_operand():
    cpu = machine("MOV R0,9\nCMP R0,10\nHALT")
    cpu.run()
    assert cpu.registers[0] == 9 and cpu.flags.cf


def test_mov_and_halt_preserve_carry_for_adc():
    cpu = machine("MOV R0,65535\nADD R0,1\nMOV R1,0\nADC R1,0\nHALT")
    cpu.run()
    assert cpu.registers[:2] == [0, 1]


def test_mul_reads_source_before_writing_overlapping_result_pair():
    cpu = machine("MOV R6,-32768\nMOV R7,-32768\nMUL R6,R7\nHALT")
    cpu.run()
    assert cpu.registers[6:8] == [0, 0x4000]


@pytest.mark.parametrize("command,setup,taken", [
    ("JMP", "NOP", True), ("JZ", "CMP R0,0", True), ("JZ", "CMP R0,1", False),
    ("JNZ", "CMP R0,1", True), ("JNZ", "CMP R0,0", False),
    ("JC", "SUB R0,1", True), ("JC", "ADD R0,1", False),
    ("JNC", "ADD R0,1", True), ("JNC", "SUB R0,1", False),
    ("JO", "MOV R0,32767\nADD R0,1", True), ("JO", "ADD R0,1", False),
    ("JNO", "ADD R0,1", True), ("JNO", "MOV R0,32767\nADD R0,1", False),
])
def test_branch_conditions(command, setup, taken):
    cpu = machine(f"{setup}\n{command} end\nMOV R1,1\nend: HALT")
    cpu.run()
    assert cpu.registers[1] == (0 if taken else 1)


def test_program_can_modify_future_instruction_in_unified_memory():
    """Записываем старшее слово будущего NOP, превращая его в HALT.

    Если CPU исполнял бы заранее разобранный список Python-объектов,
    эта проверка провалилась бы: он не заметил бы изменения кода в ОЗУ.
    """
    cpu = machine("MOV R0,0xFF00\nMOV [target+2],R0\nJMP target\n"
                  "target: NOP\nMOV R1,123\nHALT")
    cpu.run()
    assert cpu.steps == 4
    assert cpu.registers[1] == 0
    assert cpu.ir == 0xFF000000


@pytest.mark.parametrize("source", [
    "MOV R0,4096\nMOV R1,[R0]\nHALT",
    "MOV R0,3\nMOV [R0],R1\nHALT",
    "MOV R0,-1\nMOV R1,[R0]\nHALT",
    "MOV R1,16\nSAR R0,R1\nHALT",
])
def test_fault_does_not_partially_commit(source):
    cpu = machine(source)
    cpu.step()
    before, memory = cpu.snapshot(), cpu.memory.image()
    with pytest.raises(CPUFault):
        cpu.step()
    assert cpu.snapshot() == before
    assert cpu.memory.image() == memory


def test_corrupted_machine_code_is_checked_at_runtime():
    cpu = machine("NOP\nHALT")
    cpu.memory.write_word(2, 0xAB00)
    before = cpu.snapshot()
    with pytest.raises(CPUFault):
        cpu.step()
    assert cpu.snapshot() == before


def test_halt_limit_and_instruction_size():
    cpu = machine("loop: JMP loop")
    with pytest.raises(ExecutionLimit):
        cpu.run(7)
    assert cpu.steps == 7 and not cpu.halted and cpu.pc == 0
    assert cpu.step().after.steps == 8
    with pytest.raises(ValueError):
        cpu.run(0)
    halted = machine("HALT")
    halted.run(1)
    assert halted.pc == 4
    with pytest.raises(CPUFault):
        halted.step()


def test_end_of_memory_fetch():
    cpu = machine(".entry start\n.org 4092\nstart: NOP")
    cpu.step()
    assert cpu.pc == 4096
    with pytest.raises(CPUFault):
        cpu.step()


def test_memory_is_little_endian_and_word_reads_are_aligned():
    memory = Memory()
    memory.write_word(256, 0x1234)
    assert memory.image()[256:258] == b"\x34\x12"
    for address in (-2, 1, 4095, 4096):
        with pytest.raises(CPUFault):
            memory.read_word(address)
    with pytest.raises(ValueError):
        Memory(b"too short")
