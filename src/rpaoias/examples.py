"""Один набор исходников .asm используется в UI, CLI и интеграционных тестах.

Программы входят в пакет как ресурсы, поэтому работают после установки
wheel и не зависят от текущего каталога. Второй копии исходников нет.
"""

from importlib.resources import files
from pathlib import Path

EXAMPLES = {
    "sum": "Сумма массива",
    "dot_product": "Свертка двух массивов",
    "carry": "Перенос ADD/ADC",
    "overflow": "Различие CF и OF",
}


def example_source(name: str) -> str:
    if name not in EXAMPLES:
        raise ValueError(f"Неизвестный пример: {name}")
    return files("rpaoias.programs").joinpath(f"{name}.asm").read_text(encoding="utf-8")


def read_source(name_or_path: str) -> str:
    """Имя встроенного примера либо путь к пользовательскому UTF-8 исходнику."""
    if name_or_path in EXAMPLES:
        return example_source(name_or_path)
    return Path(name_or_path).read_text(encoding="utf-8-sig")
