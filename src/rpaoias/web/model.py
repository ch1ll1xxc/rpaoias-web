"""Сеанс отладчика. CPU выполняет команду; этот модуль описывает ее потоки."""

from collections import deque
from dataclasses import asdict
from threading import RLock

from rpaoias.assembler.assembler import assemble
from rpaoias.cpu.processor import CPU, StepResult
from rpaoias.cpu.word import MEMORY_BYTES, signed, join_words
from rpaoias.errors import EmulatorError
from rpaoias.examples import EXAMPLES, example_source
from rpaoias.isa.codec import decode
from rpaoias.isa.instruction import ARITHMETIC, JUMPS, Mode, Opcode
from rpaoias.ui.step_description import describe_step

HISTORY_LIMIT = 500
SOURCE_LIMIT = 100_000
DEMO_SOURCE = """; Передача данных: ОЗУ → регистры → АЛУ → ОЗУ.
; Один адрес — один байт; слово занимает два байта.
.entry start
.org 0
start:
    MOV R3, DATA       ; Получить адрес данных.
    MOV R0, [R3]      ; Прочитать первое слово через указатель.
    ADD R3, 2         ; Перейти ко второму слову.
    MOV R1, [R3]      ; Прочитать второе слово.
    ADD R0, R1        ; Сложить два регистра в АЛУ.
    MOV [RESULT], R0  ; Записать результат в ОЗУ.
    HALT

.org 0x0400
DATA:
    .word 7, 12
.org 0x0500
RESULT:
    .word 0, 0, 0
"""
EXAMPLE_NAMES = {"flow": "Потоки: 7 + 12", **EXAMPLES}


def source_for(name: str) -> str:
    if name == "flow":
        return DEMO_SOURCE
    if name not in EXAMPLES:
        raise ValueError("Неизвестный пример")
    return example_source(name)


def snapshot(cpu: CPU) -> dict:
    return asdict(cpu.snapshot())


def build_flow(step: StepResult, memory_before: bytes, source: str = "") -> dict:
    """Вычислений CPU здесь нет: результаты берутся из before/after."""
    d = describe_step(step, memory_before, source)
    i, b, a = step.instruction, step.before, step.after
    flows: list[dict] = []
    roles: list[dict] = []
    written: list[int] = []
    op = i.opcode

    def flow(phase: int, src: str, dst: str, kind: str, label: str, detail: str = ""):
        flows.append(dict(phase=phase, src=src, dst=dst, kind=kind,
                          label=label, detail=detail or label))

    def register(n: int, role: str):
        roles.append(dict(index=n, role=role))

    def w(n: int) -> str:
        return f"0x{n:04X}"

    flow(0, "pc", "memory", "address", f"адрес {w(step.address)}", "PC задает байтовый адрес выборки четырех байт.")
    flow(0, "memory", "word", "read", f"команда 0x{a.ir:08X}", "Четыре байта единой ОЗУ читаются в little-endian.")
    flow(1, "word", "decoder", "control", f"opcode 0x{int(op):02X}")
    flow(1, "decoder", "control", "control", i.assembly())
    flow(3, "word", "ir", "control", f"IR = 0x{a.ir:08X}", "IR фиксируется только после успешного завершения CPU.step().")
    flow(3, "control", "pc", "address", f"PC = {w(a.pc)}")
    operation = {"name": op.name, "a": "—", "b": "—", "result": "—", "carry": None,
                 "used": op in ARITHMETIC, "detail": d.phases[2].detail}
    if op == Opcode.STORE:
        address, _old, value = step.memory_writes[0]
        register(i.register, "source")
        if i.mode == Mode.INDIRECT:
            register(i.operand, "address")
            flow(2, f"r{i.operand}", "memory", "address", f"адрес {w(address)}")
        else:
            flow(2, "decoder", "memory", "address", f"адрес {w(address)}")
        flow(3, f"r{i.register}", "memory", "write", f"R{i.register} → ОЗУ: {w(value)}")
        operation.update(name="MOV → ОЗУ", a=f"R{i.register}: {w(value)}", result=f"ОЗУ[{w(address)}]")
    elif op in JUMPS:
        if op != Opcode.JMP:
            flow(2, "flags", "control", "control", "условие выполнено" if d.branch_taken else "условие ложно")
        operation.update(name=op.name, a=f"цель {w(i.operand)}", result=f"PC = {w(a.pc)}")
    elif op in (Opcode.NOP, Opcode.HALT):
        operation.update(result="остановка" if op == Opcode.HALT else "данные сохранены")
        if op == Opcode.HALT:
            flow(3, "control", "halt", "control", "HALTED = 1")
    else:
        src, value = "decoder", i.operand
        if i.mode == Mode.REGISTER:
            src, value = f"r{i.operand}", b.registers[i.operand]
            register(i.operand, "source")
        elif i.mode in (Mode.DIRECT, Mode.INDIRECT):
            address = i.operand if i.mode == Mode.DIRECT else b.registers[i.operand]
            src = "memory"
            value = int.from_bytes(memory_before[address:address + 2], "little")
            if i.mode == Mode.INDIRECT:
                register(i.operand, "address")
                flow(2, f"r{i.operand}", "memory", "address", f"адрес {w(address)}")
            else:
                flow(2, "decoder", "memory", "address", f"адрес {w(address)}")
        if op == Opcode.MOV:
            flow(3, src, f"r{i.register}", "read" if src == "memory" else "register", f"{w(value)} → R{i.register}")
            written.append(i.register)
            operation.update(name="MOV", a=w(value), result=f"R{i.register}: {w(a.registers[i.register])}")
        else:
            register(i.register, "source")
            flow(2, f"r{i.register}", "alu", "register", f"A: {w(b.registers[i.register])}")
            flow(2, src, "alu", "register", f"B: {w(value)}")
            operation.update(a=f"{w(b.registers[i.register])} / {signed(b.registers[i.register])}",
                             b=f"{w(value)} / {signed(value)}")
            if op == Opcode.ADC:
                operation["carry"] = int(b.flags.cf)
                flow(2, "flags", "alu", "control", f"CF вход = {int(b.flags.cf)}")
            if op != Opcode.CMP:
                written.append(i.register)
                if op == Opcode.MUL:
                    written.append(i.register + 1)
                operation["result"] = " : ".join(w(a.registers[n]) for n in reversed(written))
                for n in written:
                    flow(3, "alu", f"r{n}", "register", f"R{n} = {w(a.registers[n])}")
            else:
                operation["result"] = "только флаги"
            if not (op == Opcode.SAR and value == 0):
                flow(3, "alu", "flags", "control", "ZF / SF / CF / OF")
    for n in written:
        register(n, "target")
    return {"id": a.steps, "address": step.address, "source": source,
            "instruction": {"asm": i.assembly(), "word": a.ir, "opcode": int(op),
                            "name": op.name, "register": i.register, "mode": int(i.mode),
                            "mode_name": i.mode.name, "operand": i.operand},
            "before": asdict(b), "after": asdict(a), "flows": flows, "roles": roles,
            "operation": operation, "phases": [asdict(p) for p in d.phases],
            "changes": [asdict(c) for c in d.changes], "accesses": [asdict(x) for x in d.accesses],
            "summary": d.summary, "branch_taken": d.branch_taken,
            "memory_before": memory_before.hex()}


class Session:
    def __init__(self):
        self.lock = RLock()
        self.revision = 0
        self.history: deque[dict] = deque(maxlen=HISTORY_LIMIT)
        self.error = ""
        self.source = ""
        self.assemble(DEMO_SOURCE)

    def assemble(self, source: str) -> None:
        if not isinstance(source, str) or len(source.encode("utf-8")) > SOURCE_LIMIT:
            raise ValueError("Исходник должен быть текстом размером до 100 КБ")
        program = assemble(source)  # Не публикуем частичную сборку при ошибке.
        self.source, self.program = source, program
        self.reset()

    def reset(self) -> None:
        self.cpu = CPU(self.program.image, self.program.entry)
        self.history.clear()
        self.error = ""
        self.revision += 1

    def step(self) -> dict:
        if self.error:
            raise ValueError("Сначала сбрось CPU после ошибки исполнения")
        memory = self.cpu.memory.image()
        try:
            result = self.cpu.step()
        except EmulatorError as exc:
            self.error = str(exc)
            self.revision += 1
            raise
        line = next((row.source.strip() for row in self.program.listing if row.address == result.address), "")
        record = build_flow(result, memory, line)
        record["memory_after"] = self.cpu.memory.image().hex()
        self.history.append(record)
        self.revision += 1
        return record

    def run_to_halt(self, limit: int = 10_000) -> None:
        """Execute actual CPU instructions and retain their normal history records."""
        count = 0
        while not self.cpu.halted and count < limit:
            self.step()
            count += 1
        if not self.cpu.halted:
            raise ValueError(f"Выполнен предел {limit} инструкций без HALT; CPU сохранен.")

    def state(self, include_program: bool = False) -> dict:
        upcoming = None
        if not self.cpu.halted:
            try:
                upcoming = decode(self.cpu.memory.read_instruction(self.cpu.pc)).assembly()
            except EmulatorError:
                pass
        result = None
        if "RESULT" in self.program.symbols:
            address = self.program.symbols["RESULT"]
            if address % 2 == 0 and address + 6 <= MEMORY_BYTES:
                result = {"address": address, "value": join_words([self.cpu.memory.read_word(address + n * 2) for n in range(3)])}
        state = {"revision": self.revision, "cpu": snapshot(self.cpu), "memory": self.cpu.memory.image().hex(),
                 "error": self.error, "upcoming": upcoming, "result": result,
                 "last": self.history[-1] if self.history else None,
                 "history": [{k: row[k] for k in ("id", "address", "instruction", "summary")} for row in self.history]}
        if include_program:
            state["program"] = {"source": self.source, "entry": self.program.entry,
                                 "symbols": self.program.symbols, "listing": [asdict(x) for x in self.program.listing],
                                 "regions": self.regions()}
        return state

    def regions(self) -> list[dict]:
        # Каждая полоса — 256 байт той же единой ОЗУ. Это не аппаратные сегменты.
        regions = []
        code = {row.address // 256 for row in self.program.listing}
        for page in range(16):
            start = page * 256
            labels = [k for k, address in self.program.symbols.items() if address // 256 == page]
            data = self.program.image[start:start + 256]
            kind = "code" if page in code else ("data" if labels or any(data) else "unused")
            regions.append({"start": start, "end": start + 255, "kind": kind, "labels": labels})
        return regions
