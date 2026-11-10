"""Сравниваем программы CPU с независимым математическим эталоном Python.

Python sum используется только В ТЕСТЕ. В CPU отсутствует такая операция:
его результат строят машинные ADD/ADC/MUL в цикле из .asm-файла.
"""

import random

import pytest

from rpaoias.assembler.assembler import assemble
from rpaoias.cpu.processor import CPU
from rpaoias.cpu.word import join_words
from rpaoias.examples import example_source


def execute(name, left=None, right=None):
    program = assemble(example_source(name))
    cpu = CPU(program.image, program.entry)
    if left is not None:
        arrays = [("ARRAY" if name == "sum" else "ARRAY_A", left)]
        if right is not None:
            arrays.append(("ARRAY_B", right))
        for label, data in arrays:
            address = program.symbols[label]
            cpu.memory.write_word(address, len(data))
            for index, value in enumerate(data):
                cpu.memory.write_word(address + 2 + 2 * index, value)
    cpu.run(5000)
    address = program.symbols["RESULT"]
    result = join_words([cpu.memory.read_word(address + 2 * index) for index in range(3)])
    return result, cpu


@pytest.mark.parametrize("name,expected,steps", [("sum", 65459, 105),
                                                 ("dot_product", 2947418113, 141),
                                                 ("carry", 65536, 8)])
def test_bundled_examples(name, expected, steps):
    result, cpu = execute(name)
    assert result == expected
    assert cpu.steps == steps
    assert cpu.registers[15] == 0


@pytest.mark.parametrize("values", [[], [0], [-1], [-32768], [32767],
                                     [32767] * 15, [-32768] * 15,
                                     [-1, 1] * 7, [32767, -32768] * 7])
def test_sum_boundaries_and_header_is_not_summed(values):
    actual, cpu = execute("sum", values)
    assert actual == sum(values)
    assert cpu.registers[15] == 0


@pytest.mark.parametrize("left,right", [
    ([], []), ([0] * 10, [0] * 10), ([-1] * 10, [1] * 10),
    ([-32768] * 10, [-32768] * 10), ([32767] * 10, [32767] * 10),
    ([-32768] * 10, [32767] * 10), ([32767, -32768] * 5, [32767] * 10),
])
def test_dot_product_extremes_need_more_than_32_bits(left, right):
    actual, cpu = execute("dot_product", left, right)
    expected = sum(a * b for a, b in zip(left, right, strict=True))
    assert actual == expected
    assert cpu.registers[15] == 0


@pytest.mark.parametrize("seed", range(120))
def test_random_arrays_match_math(seed):
    rng = random.Random(seed)
    values = [rng.randint(-32768, 32767) for _ in range(rng.randint(6, 15))]
    actual, _cpu = execute("sum", values)
    assert actual == sum(values)
    left = [rng.randint(-32768, 32767) for _ in range(10)]
    right = [rng.randint(-32768, 32767) for _ in range(10)]
    actual, _cpu = execute("dot_product", left, right)
    assert actual == sum(a * b for a, b in zip(left, right, strict=True))


@pytest.mark.parametrize("a_length,b_length", [(9, 10), (11, 11), (65535, 65535)])
def test_invalid_headers_report_program_status(a_length, b_length):
    program = assemble(example_source("dot_product"))
    cpu = CPU(program.image, program.entry)
    cpu.memory.write_word(program.symbols["ARRAY_A"], a_length)
    cpu.memory.write_word(program.symbols["ARRAY_B"], b_length)
    cpu.run()
    assert cpu.registers[15] == 1


def test_reset_requires_original_memory_image_not_just_zero_registers():
    program = assemble(example_source("sum"))
    cpu = CPU(program.image, program.entry)
    cpu.run()
    cpu = CPU(program.image, program.entry)
    assert cpu.steps == 0 and cpu.registers == [0] * 16
    assert cpu.memory.read_word(program.symbols["RESULT"]) == 0
