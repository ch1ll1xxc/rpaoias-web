"""Ошибки инструментов отделены от ошибок исполняемой программы.

Ассемблер отвергает некорректный исходный текст до загрузки в CPU.
Но машинный код можно повредить уже в памяти, поэтому CPU тоже обязан
проверять инструкции. Доверять только парсеру было бы недостаточно.
"""


class EmulatorError(Exception):
    """Ожидаемая ошибка пользователя, которую CLI и UI показывают без traceback."""


class AssemblyError(EmulatorError):
    """Диагностика исходного текста с координатами, начиная с единицы."""

    def __init__(self, message: str, line: int = 1, column: int = 1) -> None:
        self.line = line
        self.column = column
        self.message = message
        super().__init__(f"Строка {line}, столбец {column}: {message}")


class CPUFault(EmulatorError):
    """Модельная авария: неверный opcode, адрес, выравнивание или операнд."""


class ExecutionLimit(EmulatorError):
    """Ограничение отладчика, а не аппаратная команда и не флаг процессора."""
