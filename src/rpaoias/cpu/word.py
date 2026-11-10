"""Разрядная сетка и дополнительный код.

Основа задания: методичка, разделы 3.1–3.2, печатные стр. 29–34.
Конкретная ширина 16 бит – проектное решение, а не требование варианта.

Python int не ограничен 16 битами. Поэтому модель сама отбрасывает разряды,
которые физически не поместились бы в регистр. При этом 0xFFFF хранится
одинаково и для unsigned 65535, и для signed -1: различается интерпретация.
"""

WORD_BITS = 16
WORD_BYTES = WORD_BITS // 8
WORD_MASK = (1 << WORD_BITS) - 1
SIGN_BIT = 1 << (WORD_BITS - 1)
SIGNED_MIN = -SIGN_BIT
SIGNED_MAX = SIGN_BIT - 1
REGISTER_COUNT = 16
MEMORY_BYTES = 4096
INSTRUCTION_BYTES = 4


def u16(value: int) -> int:
    """Оставить младшие 16 бит: арифметика по модулю 2**16."""
    return value & WORD_MASK


def signed(value: int, bits: int = WORD_BITS) -> int:
    """Прочитать битовый вектор как целое в дополнительном коде.

    Старший бит имеет вес -(2**(bits-1)), а не +(2**(bits-1)).
    Вычитание 2**bits меняет интерпретацию, но не набор хранимых битов.
    """
    if bits <= 0:
        raise ValueError("Разрядность должна быть положительной")
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def join_words(words: tuple[int, ...] | list[int], *, signed_result: bool = True) -> int:
    """Собрать число для отображения; первым передается МЛАДШЕЕ слово.

    CPU не использует эту функцию для накопления суммы. Сложение длинного
    числа выполняет программа через ADD/ADC; склейка нужна только UI,
    CLI и тестам, чтобы показать человеку итог в десятичном виде.
    """
    if not words:
        raise ValueError("Нужно хотя бы одно слово")
    value = sum(u16(word) << (WORD_BITS * index) for index, word in enumerate(words))
    return signed(value, WORD_BITS * len(words)) if signed_result else value
