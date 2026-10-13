"""Выгрузка схемы OpenAPI в файл без запущенного сервера.

Нужна там, где поднимать backend незачем или нечем: генерация
TypeScript-типов в CI и сборка production-образа витрины.

    python -m app.scripts.dump_openapi packages/api-types/openapi.json

Приложение собирается через create_app(): именно оно отдаёт /openapi.json
в рабочем режиме, поэтому расхождения между файлом и живым API нет.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Использование: python -m app.scripts.dump_openapi <файл.json>", file=sys.stderr)
        return 2

    # Импорт внутри функции: настройки читаются при импорте app.main,
    # и ошибка конфигурации должна попасть в наш вывод, а не в трейс
    # на уровне модуля.
    from app.main import create_app

    schema = create_app().openapi()
    target = Path(argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OpenAPI записан: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
