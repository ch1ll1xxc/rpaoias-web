"""АЛУ: результат одной операции и флаги этой операции.

Методичка: 2.2, 2.3 и 3.1–3.2. Точная семантика флагов нашей ISA:
ZF – результат нулевой; SF – старший бит; CF – беззнаковый перенос/заем;
OF – выход математического знакового результата за диапазон 16 бит.

CF и OF нельзя подменять друг другом. Например, 32767 + 1 дает OF=1,
CF=0, а 65535 + 1 дает CF=1, OF=0 при знаковой интерпретации -1 + 1.
Функции чистые: они не меняют память или регистры и тестируются отдельно.
"""

from dataclasses import dataclass

from rpaoias.cpu.word import SIGNED_MAX, SIGNED_MIN, WORD_MASK, signed, u16


@dataclass(frozen=True, slots=True)
class Flags:
    """Четыре однобитных состояния; bool удобнее непрозрачного целого числа."""

    zf: bool = False
    sf: bool = False
    cf: bool = False
    of: bool = False


@dataclass(frozen=True, slots=True)
class ALUResult:
    value: int
    flags: Flags


def _flags(value: int, *, carry: bool, overflow: bool) -> Flags:
    """ZF и SF относятся к сохраненным 16 битам, а не к Python int до маски."""
    return Flags(value == 0, bool(value & 0x8000), carry, overflow)


def add(left: int, right: int, carry_in: int = 0) -> ALUResult:
    """ADD при carry_in=0; ADC прибавляет входящий CF как третий бит-слагаемое."""
    if carry_in not in (0, 1):
        raise ValueError("Входящий перенос может быть только 0 или 1")
    left, right = u16(left), u16(right)
    full = left + right + carry_in
    result = u16(full)
    # Отдельно считаем знаковую сумму. Тот же битовый ответ может быть
    # корректным беззнаковым числом и переполненным знаковым числом.
    mathematical = signed(left) + signed(right) + carry_in
    return ALUResult(
        result,
        _flags(result, carry=full > WORD_MASK,
               overflow=not SIGNED_MIN <= mathematical <= SIGNED_MAX),
    )


def sub(left: int, right: int) -> ALUResult:
    """SUB и CMP используют одно вычитание; CMP только не сохраняет result.

    В нашей ISA CF=1 означает заем: unsigned left < unsigned right.
    Это выбранное соглашение, а не универсальное правило всех процессоров.
    """
    left, right = u16(left), u16(right)
    result = u16(left - right)
    mathematical = signed(left) - signed(right)
    return ALUResult(
        result,
        _flags(result, carry=left < right,
               overflow=not SIGNED_MIN <= mathematical <= SIGNED_MAX),
    )


def sar(value: int, count: int, previous: Flags) -> ALUResult:
    """Арифметический сдвиг вправо размножает знаковый бит.

    SAR x,15 превращает 16-битное x в 0x0000 или 0xFFFF. Это позволяет
    программно подготовить старшее слово при знаковом расширении.
    Для count=0 сохраняем все флаги; для 1..15 OF=0 по нашей спецификации.
    """
    if not 0 <= count < 16:
        raise ValueError("SAR допускает число сдвигов от 0 до 15")
    value = u16(value)
    if count == 0:
        return ALUResult(value, previous)
    result = u16(signed(value) >> count)
    last_shifted_bit = bool((value >> (count - 1)) & 1)
    return ALUResult(result, _flags(result, carry=last_shifted_bit, overflow=False))


def multiply(left: int, right: int) -> tuple[int, int, Flags]:
    """Знаковое 16x16 -> два 16-битных слова: low, high, flags.

    Одна машинная инструкция может иметь расширенный результат. Это
    не делает всю машину 32-битной: каждое следующее ADD остается 16-битным.
    CF=OF показывают, помещается ли произведение в ОДНО знаковое слово.
    Полные 32 бита произведения сохраняются независимо от этих флагов.
    """
    product = signed(left) * signed(right)
    low, high = u16(product), u16(product >> 16)
    does_not_fit_word = not SIGNED_MIN <= product <= SIGNED_MAX
    flags = Flags(product == 0, product < 0, does_not_fit_word, does_not_fit_word)
    return low, high, flags
