"""Пояснение завершенного шага. Читает снимки; никогда не исполняет команды."""

from dataclasses import dataclass

from rpaoias.cpu.alu import Flags
from rpaoias.cpu.processor import StepResult
from rpaoias.cpu.word import MEMORY_BYTES, signed
from rpaoias.isa.instruction import JUMPS, Mode, Opcode


@dataclass(frozen=True, slots=True)
class Change:
    name: str
    before: str
    after: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Access:
    kind: str
    address: int
    width: int
    value: int
    previous: int | None = None


@dataclass(frozen=True, slots=True)
class Phase:
    title: str
    source: str
    operation: str
    target: str
    detail: str


@dataclass(frozen=True, slots=True)
class StepDescription:
    result: StepResult
    source: str
    phases: tuple[Phase, ...]
    changes: tuple[Change, ...]
    accesses: tuple[Access, ...]
    branch_taken: bool | None = None

    @property
    def summary(self) -> str:
        visible = [c for c in self.changes if c.name not in ("PC", "IR")]
        if not visible:
            return f"PC → 0x{self.result.after.pc:04X}; данные и флаги сохранены"
        return "; ".join(f"{c.name}: {c.before} → {c.after}" for c in visible)


def word(value: int) -> str:
    return f"0x{value:04X} ({signed(value)})"


def describe_step(step: StepResult, memory_before: bytes, source: str = "") -> StepDescription:
    """memory_before используется только здесь, целые образы ОЗУ в истории не храним."""
    if len(memory_before) != MEMORY_BYTES:
        raise ValueError(f"Нужен снимок ОЗУ на {MEMORY_BYTES} байт")
    i, before, after = step.instruction, step.before, step.after
    raw = int.from_bytes(memory_before[step.address:step.address + 4], "little")
    if raw != after.ir:
        raise ValueError("Снимок памяти не соответствует исполненной инструкции")
    changes: list[Change] = []
    for n, (old, new) in enumerate(zip(before.registers, after.registers, strict=True)):
        if old != new:
            changes.append(Change(f"R{n}", f"0x{old:04X}", f"0x{new:04X}",
                                  f"Со знаком: {signed(old)} → {signed(new)}"))
    for name in ("zf", "sf", "cf", "of"):
        old, new = getattr(before.flags, name), getattr(after.flags, name)
        if old != new:
            changes.append(Change(name.upper(), str(int(old)), str(int(new)), "Флаг операции"))
    accesses = [Access("Выборка команды", step.address, 4, raw)]
    for address, old, new in step.memory_writes:
        accesses.append(Access("Запись данных", address, 2, new, old))
        if old != new:
            changes.append(Change(f"ОЗУ[0x{address:04X}]", f"0x{old:04X}", f"0x{new:04X}",
                                  f"Со знаком: {signed(old)} → {signed(new)}"))
    if before.pc != after.pc:
        changes.append(Change("PC", f"0x{before.pc:04X}", f"0x{after.pc:04X}", "Адрес следующей команды"))
    if before.ir != after.ir:
        changes.append(Change("IR", f"0x{before.ir:08X}", f"0x{after.ir:08X}", "Исполненное машинное слово"))
    if before.halted != after.halted:
        changes.append(Change("HALTED", str(int(before.halted)), str(int(after.halted)), "Процессор остановлен"))

    branch_taken = None
    if i.opcode == Opcode.STORE:
        address, old, new = step.memory_writes[0]
        left = f"R{i.register}\n{word(before.registers[i.register])}"
        action = "MOV\nЗапись слова"
        target = f"ОЗУ[0x{address:04X}]\n{word(new)}"
        detail = f"По адресу 0x{address:04X} записаны два байта. Прежнее слово: {word(old)}. Флаги сохранены."
    elif i.opcode in JUMPS:
        if i.opcode == Opcode.JMP:
            branch_taken, condition = True, "Без условия"
        else:
            flag, required = {
                Opcode.JZ: ("zf", True), Opcode.JNZ: ("zf", False),
                Opcode.JC: ("cf", True), Opcode.JNC: ("cf", False),
                Opcode.JO: ("of", True), Opcode.JNO: ("of", False),
            }[i.opcode]
            value = getattr(before.flags, flag)
            branch_taken = value == required
            condition = f"{flag.upper()} = {int(value)}\nНужно: {int(required)}"
        left = condition
        action = f"{i.opcode.name}\n" + ("Переход выполнен" if branch_taken else "Переход не выполнен")
        target = f"PC\n0x{after.pc:04X}"
        detail = (f"Цель перехода: 0x{i.operand:04X}. "
                  f"После команды PC = 0x{after.pc:04X}. Регистры данных и флаги сохранены.")
    elif i.opcode in (Opcode.HALT, Opcode.NOP):
        left = f"PC до команды\n0x{before.pc:04X}"
        action = i.opcode.name
        target = f"PC после команды\n0x{after.pc:04X}"
        detail = ("HALT установил состояние остановки. Следующая команда не выполняется."
                  if after.halted else "NOP сохранил данные и флаги. PC продвинулся на четыре байта.")
    else:
        if i.mode == Mode.REGISTER:
            value = before.registers[i.operand]
            origin = f"R{i.operand} = {word(value)}"
        elif i.mode == Mode.IMMEDIATE:
            value = i.operand
            origin = f"Литерал {word(value)}"
        else:
            address = i.operand if i.mode == Mode.DIRECT else before.registers[i.operand]
            value = int.from_bytes(memory_before[address:address + 2], "little")
            accesses.append(Access("Чтение данных", address, 2, value))
            origin = f"ОЗУ[0x{address:04X}] = {word(value)}"
            if i.mode == Mode.INDIRECT:
                origin = f"R{i.operand} → 0x{address:04X}\n" + origin
        left = origin
        if i.opcode != Opcode.MOV:
            left = f"R{i.register} = {word(before.registers[i.register])}\n{origin}"
        action = i.opcode.name
        target = f"R{i.register}\n{word(after.registers[i.register])}"
        if i.opcode == Opcode.MOV:
            detail = "MOV скопировал значение в регистр. Все четыре флага сохранены."
        elif i.opcode == Opcode.CMP:
            action = "CMP\nСравнение"
            target = "Флаги\n" + flags_text(after.flags)
            detail = f"CMP обновил флаги вычитания. Значение R{i.register} осталось прежним."
        elif i.opcode == Opcode.MUL:
            target = f"R{i.register + 1}:R{i.register}\n0x{after.registers[i.register + 1]:04X}:{after.registers[i.register]:04X}"
            detail = ("Знаковое произведение записано в два регистра: старшее слово и младшее слово. "
                      "Оба операнда прочитаны до записи результата, даже при совпадении регистров.")
        elif i.opcode == Opcode.ADC:
            left += f"\nВходящий CF = {int(before.flags.cf)}"
            detail = "ADC использовал входящий перенос. Результат и новые флаги взяты из снимка CPU после команды."
        elif i.opcode == Opcode.SAR:
            action = f"SAR\nСдвиг на {value}"
            detail = ("Сдвиг на ноль сохраняет регистр и флаги." if value == 0 else
                      "Арифметический сдвиг повторяет знаковый бит слева. CF хранит последний вытесненный бит.")
        else:
            detail = "В регистр записаны младшие 16 бит результата. Флаги взяты из снимка CPU после команды."

    code_bytes = memory_before[step.address:step.address + 4].hex(" ").upper()
    phases = (
        Phase("Выборка", f"PC\n0x{step.address:04X}", "Чтение 4 байт", f"ОЗУ\n{code_bytes}",
              f"До команды память содержала слово 0x{raw:08X}. Порядок байтов: little-endian. "
              "В этой модели IR фиксируется после успешного завершения всей команды."),
        Phase("Разбор", f"Машинное слово\n0x{raw:08X}", "Декодирование", i.assembly(),
              f"opcode[31:24] = 0x{int(i.opcode):02X}; reg[23:20] = {i.register}; "
              f"mode[19:18] = {int(i.mode):02b}; reserve[17:16] = 00; operand[15:0] = 0x{i.operand:04X}."),
        Phase("Операция", left, action, target, detail),
        Phase("Запись", f"Состояние до\nPC = 0x{before.pc:04X}", "Фиксация результата", target,
              f"Команда завершена. PC = 0x{after.pc:04X}; IR = 0x{after.ir:08X}. "
              + ("CPU остановлен HALT." if after.halted else "CPU готов к следующему шагу.")
              + " Измененные значения перечислены ниже."),
    )
    return StepDescription(step, source, phases, tuple(changes), tuple(accesses), branch_taken)


def flags_text(flags: Flags) -> str:
    return "  ".join(f"{key.upper()}={int(getattr(flags, key))}" for key in ("zf", "sf", "cf", "of"))
