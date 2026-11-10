"""Единая байтовая память: программная модель архитектуры фон Неймана.

Методичка: 1.1, стр. 5–8; выбор архитектуры: табл. 4.1, стр. 38.
Команды и данные лежат в ОДНОМ bytearray. Никакого скрытого списка готовых
Python-команд для исполнения нет: fetch каждый раз читает байты из ОЗУ.

Наши решения: 4096 байт, little-endian, выравнивание слов на 2 байта,
инструкций на 4. Поэтому переход к следующему элементу массива – +2,
а не +1. Разрядность данных и размер адресуемой ячейки – разные понятия.
"""

from rpaoias.cpu.word import MEMORY_BYTES, u16
from rpaoias.errors import CPUFault


class Memory:
    def __init__(self, image: bytes | None = None) -> None:
        if image is not None and len(image) != MEMORY_BYTES:
            raise ValueError(f"Образ памяти должен содержать {MEMORY_BYTES} байт")
        self._data = bytearray(image if image is not None else bytes(MEMORY_BYTES))

    @staticmethod
    def check(address: int, width: int, alignment: int) -> None:
        """Проверяем весь диапазон, не только первый байт обращения.

        Отрицательные индексы Python означают доступ с конца массива.
        В модели процессора это было бы скрытой ошибкой, поэтому запрещаем.
        """
        if address < 0 or address + width > MEMORY_BYTES:
            raise CPUFault(f"Выход за ОЗУ: адрес {address}, размер доступа {width} байт")
        if address % alignment:
            raise CPUFault(f"Адрес 0x{address:04X} не выровнен на {alignment} байт")

    def read_word(self, address: int) -> int:
        self.check(address, 2, 2)
        # Младший байт расположен по меньшему адресу: little-endian.
        return int.from_bytes(self._data[address:address + 2], "little")

    def write_word(self, address: int, value: int) -> None:
        self.check(address, 2, 2)
        self._data[address:address + 2] = u16(value).to_bytes(2, "little")

    def read_instruction(self, address: int) -> int:
        self.check(address, 4, 4)
        return int.from_bytes(self._data[address:address + 4], "little")

    def image(self) -> bytes:
        """Неизменяемая копия для reset/тестов; не открываем bytearray интерфейсу."""
        return bytes(self._data)
