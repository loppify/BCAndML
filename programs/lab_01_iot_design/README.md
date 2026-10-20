# Лабораторна робота № 1: проєкт системи IoT IDS

Вихідний код проєктної роботи для теми № 28: аналіз мережевого трафіку набору ToN_IoT і підготовка архітектури системи виявлення вторгнень у симульованому IoT-середовищі.

## Структура

- `code/src/`: завантаження набору даних і аналіз трафіку.
- `code/notebooks/`: відтворюваний Jupyter notebook.
- `code/diagrams/`: вихідні файли схем у форматі Graphviz.
- `code/docs/adr/`: архітектурні рішення.
- `code/requirements.txt`: залежності аналізу.

Набір даних не зберігається в репозиторії. За потреби скрипт завантажує CSV у `code/data/raw/` і перевіряє розмір та SHA-256 перед аналізом.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r code/requirements.txt
python code/src/analysis.py
jupyter notebook code/notebooks/ton_iot_initial_analysis.ipynb
```

Скрипт аналізує баланс класів, типи атак, числові ознаки, пропуски й дублікати. Моделі оцінюються на груповому розбитті за адресою джерела. Згенеровані графіки та підсумки записуються в `images/` і `artifacts/` відповідно.
