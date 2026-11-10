"""Отдельно проверяем синтаксис, таблицу меток и ограничения ISA."""

import pytest

from rpaoias.assembler.assembler import assemble
from rpaoias.assembler.lexer import tokenize
from rpaoias.errors import AssemblyError
from rpaoias.isa.codec import decode
from rpaoias.isa.instruction import Mode


def test_tokens_have_source_coordinates():
    tokens = tokenize("  MOV R2, [R3] ; comment", 5)
    assert [token.text for token in tokens] == ["MOV", "R2", ",", "[", "R3", "]"]
    assert tokens[0].line == 5 and tokens[0].column == 3


def test_forward_label_uses_byte_address_not_line_number():
    program = assemble("JMP end\nNOP\n; пустая строка\nend: HALT")
    assert program.symbols["END"] == 8
    assert decode(program.listing[0].word).operand == 8


def test_labels_directives_and_signed_words():
    program = assemble(".entry start\n.org 16\nstart: MOV R0,[item+2]\nHALT\n"
                       ".org 256\nitem: .word -1, 0x1234, 0b10, +7, 0008")
    assert program.entry == 16
    assert program.symbols["ITEM"] == 256
    assert program.image[256:260] == bytes.fromhex("ffff3412")
    assert decode(program.listing[0].word).operand == 258


def test_case_insensitive_names_and_comments():
    program = assemble(".ENTRY Start\nstart: mOv r0,-1 // negative\nHaLt")
    assert decode(program.listing[0].word).operand == 65535
    assert decode(program.listing[0].word).mode == Mode.IMMEDIATE


@pytest.mark.parametrize("source", [
    "", "; only a comment", ".word 1", "unknown R0,1", "MOV R0", "HALT R0", "NOP,", "MOV R0,",
    "MOV ,R0", "MOV R0,,1", "MOV R0,[R1", "MOV R0,R1]", "MOV R0,[[R1]]",
    "MOV R0,[]", "MOV R0,@", "MOV R0,65536", "MOV R0,-32769", "MOV R16,1",
    "MOV R0,R16", "MOV R0,[R16]", "MOV [256],[258]", "MOV [256],1",
    "ADD R0,[256]", "ADD [256],R0", "MUL R3,R1", "SAR R0,16",
    "JMP nowhere", "JMP 3", "JMP -4", "JMP 4096", "MOV R0,[4096]",
    "MOV R0,[3]", "MOV R0,1*2", "MOV R0,1+", "MOV R0,1++2", "MOV R0,R1 R2",
    "a: NOP\na: HALT", "R0: HALT", ".unknown 1", ".org", ".word",
    ".org -1\nHALT", ".org 4096\nHALT", ".org 2\nHALT",
    ".org 1\n.word 1\nHALT", "a: .org 0\nHALT",
    ".org a\na: HALT", ".entry 0\n.entry 0\nHALT",
    ".entry data\nHALT\ndata: .word 1", "HALT\n.org 0\n.word 1",
    "HALT\n.org 4094\n.word 1,2", "HALT\n.word 65536", "STORE R0,1",
])
def test_bad_source_has_controlled_diagnostic(source):
    with pytest.raises(AssemblyError):
        assemble(source)


def test_error_keeps_line_number():
    with pytest.raises(AssemblyError) as caught:
        assemble("NOP\nNOP\nMOV R16,1")
    assert caught.value.line == 3


def test_extremely_long_number_is_a_source_error():
    with pytest.raises(AssemblyError):
        assemble("MOV R0," + "9" * 10000)
