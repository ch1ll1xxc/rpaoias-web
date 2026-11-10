"""Тесты как маленькие опыты: каждый фиксирует конкретное правило арифметики."""

import random

import pytest

from rpaoias.cpu.alu import Flags, add, multiply, sar, sub
from rpaoias.cpu.word import join_words, signed, u16


@pytest.mark.parametrize("bits,value,expected", [
    (16, 0, 0), (16, 32767, 32767), (16, 32768, -32768), (16, 65535, -1),
    (32, 0xFFFFFFFF, -1), (48, 0xFFFFFFFFFFFF, -1),
])
def test_same_bits_different_signed_interpretation(bits, value, expected):
    assert signed(value, bits) == expected


def test_word_width_is_enforced():
    assert u16(65536) == 0
    assert u16(-1) == 65535
    assert join_words([0, 1, 0]) == 65536
    assert join_words([0xFFFF] * 3) == -1
    with pytest.raises(ValueError):
        signed(0, 0)
    with pytest.raises(ValueError):
        join_words([])


@pytest.mark.parametrize("left,right,carry,result,flags", [
    (0, 0, 0, 0, Flags(True, False, False, False)),
    (32767, 1, 0, 32768, Flags(False, True, False, True)),
    (65535, 1, 0, 0, Flags(True, False, True, False)),
    (32768, 65535, 0, 32767, Flags(False, False, True, True)),
    (65535, 0, 1, 0, Flags(True, False, True, False)),
    (32767, 0, 1, 32768, Flags(False, True, False, True)),
    (0, 65535, 1, 0, Flags(True, False, True, False)),
    (65535, 65535, 1, 65535, Flags(False, True, True, False)),
])
def test_carry_is_not_signed_overflow(left, right, carry, result, flags):
    actual = add(left, right, carry)
    assert actual.value == result
    assert actual.flags == flags


@pytest.mark.parametrize("left,right,result,flags", [
    (0, 1, 65535, Flags(False, True, True, False)),
    (1, 1, 0, Flags(True, False, False, False)),
    (32768, 1, 32767, Flags(False, False, False, True)),
    (32767, 65535, 32768, Flags(False, True, True, True)),
])
def test_borrow_and_signed_subtraction(left, right, result, flags):
    actual = sub(left, right)
    assert actual.value == result
    assert actual.flags == flags


@pytest.mark.parametrize("left", [-32768, -32767, -1, 0, 1, 32767])
@pytest.mark.parametrize("right", [-32768, -32767, -1, 0, 1, 32767])
def test_signed_product_has_two_halves(left, right):
    low, high, flags = multiply(left, right)
    assert join_words([low, high]) == left * right
    assert flags.cf == flags.of == (not -32768 <= left * right <= 32767)
    assert flags.zf == (left * right == 0)
    assert flags.sf == (left * right < 0)


@pytest.mark.parametrize("value", [-32768, -19, -1, 0, 1, 32767])
def test_sar_produces_sign_extension(value):
    assert sar(value, 15, Flags()).value == (0xFFFF if value < 0 else 0)


def test_zero_shift_preserves_flags():
    previous = Flags(True, True, True, True)
    assert sar(123, 0, previous).flags is previous
    assert sar(3, 1, Flags()).flags.cf
    with pytest.raises(ValueError):
        sar(1, 16, previous)
    with pytest.raises(ValueError):
        add(1, 1, 2)


def test_random_add_adc_sub_against_mathematical_definition():
    """Фиксированный seed делает найденную ошибку воспроизводимой."""
    rng = random.Random(2048)
    for _ in range(3000):
        left, right = rng.randrange(65536), rng.randrange(65536)
        carry = rng.randrange(2)
        actual = add(left, right, carry)
        mathematical = signed(left) + signed(right) + carry
        assert actual.value == (left + right + carry) % 65536
        assert actual.flags.cf == (left + right + carry >= 65536)
        assert actual.flags.of == (mathematical < -32768 or mathematical > 32767)
        difference = sub(left, right)
        assert difference.value == (left - right) % 65536
        assert difference.flags.cf == (left < right)
