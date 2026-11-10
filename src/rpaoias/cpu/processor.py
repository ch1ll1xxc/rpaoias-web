"""Покомандная модель CPU: fetch -> decode -> execute -> commit.

Основа: методичка, 4.1 и 4.3. Не моделируем такты, электрические шины,
кеши или конвейер. Один step() – одна завершенная машинная инструкция.
Чтение команды идет из той же памяти, в которую MOV записывает данные.

Правило PC нашей модели: перед step он указывает на исполняемую команду,
после успешного step – на следующую. IR хранит последнюю исполненную
инструкцию, поэтому UI явно различает IR и команду по новому PC.
"""

from dataclasses import dataclass

from rpaoias.cpu import alu
from rpaoias.cpu.alu import Flags
from rpaoias.cpu.memory import Memory
from rpaoias.cpu.word import INSTRUCTION_BYTES, REGISTER_COUNT
from rpaoias.errors import CPUFault, ExecutionLimit
from rpaoias.isa.codec import decode
from rpaoias.isa.instruction import JUMPS, Instruction, Mode, Opcode


@dataclass(frozen=True, slots=True)
class Snapshot:
    registers: tuple[int, ...]
    pc: int
    ir: int
    flags: Flags
    halted: bool
    steps: int


@dataclass(frozen=True, slots=True)
class StepResult:
    """Результат шага для UI/CLI: они не должны заново исполнять команду."""

    address: int
    instruction: Instruction
    before: Snapshot
    after: Snapshot
    # Тройки: адрес слова, прежнее значение, новое значение.
    memory_writes: tuple[tuple[int, int, int], ...] = ()


class CPU:
    def __init__(self, image: bytes | None = None, entry: int = 0) -> None:
        Memory.check(entry, INSTRUCTION_BYTES, INSTRUCTION_BYTES)
        self.memory = Memory(image)
        self.registers = [0] * REGISTER_COUNT
        self.pc = entry
        self.ir = 0
        self.flags = Flags()
        self.halted = False
        self.steps = 0

    def snapshot(self) -> Snapshot:
        """Копия регистров не позволяет интерфейсу изменить CPU через снимок."""
        return Snapshot(tuple(self.registers), self.pc, self.ir,
                        self.flags, self.halted, self.steps)

    def _operand(self, instruction: Instruction) -> int:
        """Один и тот же operand может быть числом, номером регистра или адресом.

        Непосредственно 12 -> число 12. R12 -> значение регистра R12.
        [12] -> слово памяти по адресу 12. [R12] -> сначала адрес из R12,
        затем слово памяти по этому адресу. Эти случаи нельзя смешивать.
        """
        match instruction.mode:
            case Mode.IMMEDIATE:
                return instruction.operand
            case Mode.REGISTER:
                return self.registers[instruction.operand]
            case Mode.DIRECT:
                return self.memory.read_word(instruction.operand)
            case Mode.INDIRECT:
                return self.memory.read_word(self.registers[instruction.operand])
        raise CPUFault("Неподдерживаемая адресация")

    def step(self) -> StepResult:
        """Выполнить одну команду. При CPUFault архитектурное состояние неизменно.

        Сначала вычисляем изменения во временных переменных и проверяем
        адреса. Только затем публикуем их. Это упрощает отладку: неверная
        инструкция не успеет наполовину испортить регистры или память.
        Это удобное свойство нашего эмулятора, не требование методички.
        """
        if self.halted:
            raise CPUFault("Процессор остановлен HALT; перед новым запуском нужен сброс")
        before = self.snapshot()
        word = self.memory.read_instruction(self.pc)  # FETCH: настоящие байты ОЗУ.
        instruction = decode(word)                  # DECODE: поля, режимы, ограничения.
        op = instruction.opcode
        registers = self.registers.copy()
        flags = self.flags
        halted = False
        next_pc = self.pc + INSTRUCTION_BYTES
        writes: list[tuple[int, int, int]] = []

        # EXECUTE. Никаких специальных веток "посчитать сумму массива" здесь
        # нет: цикл и длинная арифметика целиком находятся в .asm-программе.
        if op == Opcode.HALT:
            halted = True
        elif op == Opcode.NOP:
            pass
        elif op in JUMPS:
            take = {
                Opcode.JMP: True,
                Opcode.JZ: flags.zf,
                Opcode.JNZ: not flags.zf,
                Opcode.JC: flags.cf,
                Opcode.JNC: not flags.cf,
                Opcode.JO: flags.of,
                Opcode.JNO: not flags.of,
            }[op]
            if take:
                next_pc = instruction.operand
        elif op == Opcode.STORE:
            address = (instruction.operand if instruction.mode == Mode.DIRECT
                       else self.registers[instruction.operand])
            # Проверка и чтение прежнего значения выполняются до commit.
            previous = self.memory.read_word(address)
            writes.append((address, previous, self.registers[instruction.register]))
        else:
            left = self.registers[instruction.register]
            right = self._operand(instruction)
            if op == Opcode.MOV:
                # MOV сохраняет флаги. Это позволяет переносить части числа
                # между регистрами, не уничтожая CF между ADD и ADC.
                registers[instruction.register] = right
            elif op == Opcode.MUL:
                low, high, flags = alu.multiply(left, right)
                # Приемник MUL четный; старшая половина идет в следующий РОН.
                # Оба исходных значения уже прочитаны, поэтому MUL R6,R7
                # корректен, хотя R7 затем перезаписывается старшей половиной.
                registers[instruction.register] = low
                registers[instruction.register + 1] = high
            else:
                if op == Opcode.ADD:
                    result = alu.add(left, right)
                elif op == Opcode.ADC:
                    result = alu.add(left, right, int(flags.cf))
                elif op in (Opcode.SUB, Opcode.CMP):
                    result = alu.sub(left, right)
                elif op == Opcode.SAR:
                    if not 0 <= right <= 15:
                        raise CPUFault("SAR допускает число сдвигов от 0 до 15")
                    result = alu.sar(left, right, flags)
                else:
                    raise CPUFault(f"Не реализован opcode {op.name}")
                flags = result.flags
                if op != Opcode.CMP:
                    registers[instruction.register] = result.value

        # COMMIT: здесь все потенциально ошибочные обращения уже проверены.
        for address, _previous, value in writes:
            self.memory.write_word(address, value)
        self.registers = registers
        self.flags = flags
        self.pc = next_pc
        self.ir = word
        self.halted = halted
        self.steps += 1
        return StepResult(before.pc, instruction, before, self.snapshot(), tuple(writes))

    def run(self, max_steps: int = 100_000) -> Snapshot:
        """Пакетный запуск для CLI/тестов. UI вызывает step через QTimer.

        Лимит относится к этому вызову run и спасает от бесконечного JMP.
        Исчерпание лимита не ставит HALT: программу можно продолжить пошагово.
        """
        if max_steps <= 0:
            raise ValueError("Лимит должен быть положительным")
        for _ in range(max_steps):
            if self.halted:
                return self.snapshot()
            self.step()
        if not self.halted:
            raise ExecutionLimit(f"Выполнено {max_steps} команд без HALT; запуск приостановлен")
        return self.snapshot()
