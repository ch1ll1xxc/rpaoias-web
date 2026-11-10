"""Пояснение шага проверяем на реальном CPU без зависимости от Qt."""
from dataclasses import FrozenInstanceError

import pytest

from rpaoias.assembler.assembler import assemble
from rpaoias.cpu.processor import CPU
from rpaoias.cpu.word import MEMORY_BYTES
from rpaoias.examples import example_source
from rpaoias.ui.step_description import describe_step


def run_descriptions(source):
    program = assemble(source)
    cpu = CPU(program.image, program.entry)
    results = []
    for _ in range(2000):
        if cpu.halted:
            return cpu, results
        image = cpu.memory.image()
        step = cpu.step()
        snapshot, current_memory = cpu.snapshot(), cpu.memory.image()
        result = describe_step(step, image)
        assert cpu.snapshot() == snapshot
        assert cpu.memory.image() == current_memory
        results.append(result)
    raise AssertionError("Пример не достиг HALT")


@pytest.mark.parametrize("name", ["sum", "dot_product", "carry", "overflow"])
def test_all_bundled_steps_have_four_phases_and_do_not_mutate_cpu(name):
    cpu, records = run_descriptions(example_source(name))
    assert cpu.halted
    assert len(records) == cpu.steps
    for record in records:
        assert len(record.phases) == 4
        assert record.accesses[0].kind == "Выборка команды"
        assert record.accesses[0].width == 4
        assert record.accesses[0].value == record.result.after.ir


def test_mov_read_uses_address_and_value_before_step():
    _, records = run_descriptions("MOV R2,data\nMOV R2,[R2]\nHALT\n.org 256\ndata: .word 7")
    record = records[1]
    access = next(a for a in record.accesses if a.kind == "Чтение данных")
    assert access.address == 256 and access.value == 7 and access.width == 2
    assert "R2 → 0x0100" in record.phases[2].source
    assert record.result.after.registers[2] == 7


def test_write_of_same_value_is_still_an_access_not_a_change():
    _, records = run_descriptions("MOV R1,7\nMOV [256],R1\nHALT\n.org 256\n.word 7")
    record = records[1]
    access = next(a for a in record.accesses if a.kind == "Запись данных")
    assert access.previous == access.value == 7
    assert not any(change.name.startswith("ОЗУ") for change in record.changes)


def test_fetch_uses_memory_before_self_modifying_instruction():
    # STORE перезаписывает собственное старшее слово, уже прочитанное при fetch.
    _, records = run_descriptions("MOV R0,0xFF00\nMOV [6],R0\nHALT")
    record = records[1]
    assert record.result.after.ir != 0xFF000006
    assert record.accesses[0].value == record.result.after.ir
    assert any(a.address == 6 and a.kind == "Запись данных" for a in record.accesses)


def test_future_modified_instruction_is_actually_halt():
    cpu, records = run_descriptions("MOV R0,0xFF00\nMOV [target+2],R0\nJMP target\ntarget: NOP\nHALT")
    assert cpu.steps == 4
    assert records[-1].result.instruction.assembly() == "HALT"
    assert records[-1].accesses[0].value == 0xFF000000


@pytest.mark.parametrize("jump,setup,taken", [
    ("JZ", "CMP R0,0", True), ("JZ", "CMP R0,1", False),
    ("JNZ", "CMP R0,0", False), ("JNZ", "CMP R0,1", True),
    ("JC", "SUB R0,1", True), ("JC", "ADD R0,1", False),
    ("JNC", "SUB R0,1", False), ("JNC", "ADD R0,1", True),
    ("JO", "MOV R0,32767\nADD R0,1", True), ("JO", "ADD R0,1", False),
    ("JNO", "MOV R0,32767\nADD R0,1", False), ("JNO", "ADD R0,1", True),
])
def test_branch_taken_even_when_target_equals_fallthrough(jump, setup, taken):
    _, records = run_descriptions(f"{setup}\n{jump} end\nend: HALT")
    record = records[-2]
    assert record.branch_taken is taken
    assert record.result.after.pc == record.result.before.pc + 4


def test_adc_uses_incoming_carry():
    _, records = run_descriptions("MOV R0,65535\nADD R0,1\nADC R1,0\nHALT")
    record = records[2]
    assert "Входящий CF = 1" in record.phases[2].source
    assert "0x0001" in record.phases[2].target
    assert record.result.before.flags.cf and not record.result.after.flags.cf


def test_mul_reads_both_registers_before_overlapping_write():
    _, records = run_descriptions("MOV R6,3\nMOV R7,4\nMUL R6,R7\nHALT")
    phase = records[2].phases[2]
    assert "R6 = 0x0003" in phase.source and "R7 = 0x0004" in phase.source
    assert "0x0000:000C" in phase.target


def test_cmp_does_not_report_register_write():
    _, records = run_descriptions("MOV R0,1\nCMP R0,2\nHALT")
    record = records[1]
    assert not any(c.name == "R0" for c in record.changes)
    assert "Флаги" in record.phases[2].target


def test_sar_zero_keeps_flags():
    _, records = run_descriptions("SUB R0,1\nSAR R0,0\nHALT")
    record = records[1]
    assert "ноль" in record.phases[2].detail
    assert not any(c.name in {"ZF", "CF", "SF", "OF", "R0"} for c in record.changes)


def test_halt_has_halted_change_and_pc_after_halt():
    _, records = run_descriptions("HALT")
    assert any(c.name == "HALTED" and c.after == "1" for c in records[0].changes)
    assert records[0].result.after.pc == 4


def test_description_rejects_wrong_memory_snapshot():
    program = assemble("HALT")
    cpu = CPU(program.image)
    step = cpu.step()
    with pytest.raises(ValueError):
        describe_step(step, b"")
    with pytest.raises(ValueError):
        describe_step(step, bytes(MEMORY_BYTES))


def test_history_entry_is_immutable():
    _, records = run_descriptions("HALT")
    with pytest.raises(FrozenInstanceError):
        records[0].source = "changed"
