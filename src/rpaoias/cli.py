"""CLI позволяет изучать и проверять CPU без установки графики.

Листинг – результат трансляции, трасса – результат реального исполнения.
Они не одно и то же: цикл появляется в листинге один раз, а в трассе
повторяется столько раз, сколько его выполнил процессор.
"""

import argparse
import sys
from pathlib import Path

from rpaoias.assembler.assembler import Program, assemble
from rpaoias.cpu.processor import CPU, StepResult
from rpaoias.cpu.word import join_words, signed
from rpaoias.errors import EmulatorError, ExecutionLimit
from rpaoias.examples import EXAMPLES, read_source


def trace_line(step: StepResult) -> str:
    changes = [f"R{i}: {old:04X}->{new:04X}"
               for i, (old, new) in enumerate(zip(step.before.registers, step.after.registers, strict=True))
               if old != new]
    changes.extend(f"[{addr:04X}]: {old:04X}->{new:04X}"
                   for addr, old, new in step.memory_writes)
    flags = step.after.flags
    return (f"{step.address:04X}  {step.instruction.assembly():26} "
            f"PC->{step.after.pc:04X}  "
            f"Z{int(flags.zf)} S{int(flags.sf)} C{int(flags.cf)} O{int(flags.of)}  "
            + "; ".join(changes))


def _result(cpu: CPU, program: Program, symbol: str | None, words: int) -> None:
    if symbol is None:
        symbol = "RESULT" if "RESULT" in program.symbols else None
    if symbol is not None:
        name = symbol.upper()
        if name not in program.symbols:
            raise ValueError(f"В программе нет метки {symbol}")
        address = program.symbols[name]
        parts = [cpu.memory.read_word(address + 2 * i) for i in range(words)]
        print(f"{name} ({words * 16} бит, signed): {join_words(parts)}")
        print("Слова low -> high:", " ".join(f"{word:04X}" for word in parts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Учебный CPU РПАО ИАС, вариант 2")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="Оконный отладчик; требуется extra gui")
    runner = commands.add_parser("run", help="Исполнить встроенный пример или .asm-файл")
    runner.add_argument("source", help=f"Путь или пример: {', '.join(EXAMPLES)}")
    runner.add_argument("--trace", action="store_true", help="Показывать каждый исполненный шаг")
    runner.add_argument("--max-steps", type=int, default=100_000)
    runner.add_argument("--result", help="Метка результата; по умолчанию RESULT, если она существует")
    runner.add_argument("--words", type=int, default=3, help="Число 16-битных слов результата, low first")
    compiler = commands.add_parser("assemble", help="Напечатать листинг и при необходимости сохранить ОЗУ")
    compiler.add_argument("source")
    compiler.add_argument("-o", "--output", type=Path, help="Файл полного образа ОЗУ на 4096 байт")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "gui":
            try:
                from rpaoias.ui.window import launch
            except ModuleNotFoundError as exc:
                if exc.name and exc.name.startswith("PySide6"):
                    print("Не установлен PySide6. Запуск: uv run --extra gui rpaoias gui", file=sys.stderr)
                    return 2
                raise
            return launch()
        program = assemble(read_source(arguments.source))
        if arguments.command == "assemble":
            print(f"Точка входа: 0x{program.entry:04X}")
            print("ADDR  WORD      SOURCE")
            for row in program.listing:
                print(f"{row.address:04X}  {row.word:08X}  {row.source.strip()}")
            if arguments.output:
                arguments.output.write_bytes(program.image)
                print(f"Образ ОЗУ: {arguments.output} (точка входа не хранится в .bin)")
            return 0
        if arguments.max_steps <= 0 or not 1 <= arguments.words <= 128:
            raise ValueError("Нужен положительный лимит шагов и число слов от 1 до 128")
        cpu = CPU(program.image, program.entry)
        if arguments.trace:
            for _ in range(arguments.max_steps):
                if cpu.halted:
                    break
                print(trace_line(cpu.step()))
            if not cpu.halted:
                raise ExecutionLimit("Лимит шагов исчерпан; HALT не достигнут")
        else:
            cpu.run(arguments.max_steps)
        print(f"HALT; исполнено инструкций: {cpu.steps}; PC=0x{cpu.pc:04X}; IR=0x{cpu.ir:08X}")
        print(f"ZF={int(cpu.flags.zf)} SF={int(cpu.flags.sf)} CF={int(cpu.flags.cf)} OF={int(cpu.flags.of)}")
        for index, value in enumerate(cpu.registers):
            print(f"R{index:<2} 0x{value:04X}  signed={signed(value):>7}  unsigned={value:>5}")
        _result(cpu, program, arguments.result, arguments.words)
        # Соглашение R15=статус относится только к двум встроенным заданиям.
        if arguments.source in ("sum", "dot_product") and cpu.registers[15]:
            print("Программа обнаружила неверные заголовки массивов (R15 != 0)", file=sys.stderr)
            return 3
        return 0
    except (EmulatorError, ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
