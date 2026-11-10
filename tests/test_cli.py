"""CLI – тоже пользовательский интерфейс: проверяем результаты и коды возврата."""

from rpaoias.cli import main


def test_run_and_trace(capsys):
    assert main(["run", "carry", "--trace"]) == 0
    text = capsys.readouterr().out
    assert "ADC R1" in text and "65536" in text


def test_assemble_exports_full_image(tmp_path, capsys):
    path = tmp_path / "cpu.bin"
    assert main(["assemble", "sum", "-o", str(path)]) == 0
    assert path.stat().st_size == 4096
    assert "Точка входа" in capsys.readouterr().out


def test_bad_input_returns_error_not_traceback(tmp_path, capsys):
    source = tmp_path / "bad.asm"
    source.write_text("MOV R16,1", encoding="utf-8")
    assert main(["run", str(source)]) == 2
    assert "Строка 1" in capsys.readouterr().err
    assert main(["run", "sum", "--max-steps", "0"]) == 2
    assert main(["run", "sum", "--result", "missing"]) == 2


def test_execution_limit_and_missing_file(capsys):
    assert main(["run", "sum", "--max-steps", "1"]) == 2
    assert main(["run", "sum", "--trace", "--max-steps", "1"]) == 2
    assert main(["run", "definitely_absent_54d31.asm"]) == 2
    assert capsys.readouterr().err
