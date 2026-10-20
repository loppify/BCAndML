from __future__ import annotations

from pathlib import Path

import nbformat
from nbclient import NotebookClient


CODE = Path(__file__).resolve().parents[1]
PROJECT = CODE.parent
NOTEBOOK_PATH = CODE / "notebooks" / "ton_iot_initial_analysis.ipynb"
IMAGE_NAMES = [
    ("class_distribution.png", "Розподіл бінарного класу", "У вибірці є 42 040 нормальних і 148 434 атакувальних записів після видалення точних дублікатів. Частка атаків більша, тому для оцінювання важливо аналізувати precision, recall і F1, а не лише accuracy."),
    ("attack_types.png", "Розподіл типів атак", "У наборі представлені дев'ять категорій атак. MITM має найменше прикладів, тому в наступній роботі варто перевіряти класові метрики, а для багатокласового завдання застосовувати зважування або окремо обговорити малий обсяг MITM."),
    ("source_ip_grouping.png", "Мітки за адресами джерела", "Класи розподілені нерівномірно між адресами джерела. IP-адреси не подаються моделі як ознаки; записи однієї адреси залишаються в одній частині групового розбиття, щоб зменшити витік і перевірити перенесення на невідомі джерела."),
    ("numeric_distributions.png", "Розподіли числових ознак", "Тривалість, обсяги байтів і кількість пакетів мають довгі праві хвости. Для первинної візуалізації застосовано log1p; у конвеєрі модельної підготовки числові значення очищаються від нескінченностей, а Logistic Regression масштабує ознаки."),
    ("missing_duplicates.png", "Пропуски й дублікати", "Пропущених значень у завантаженому файлі немає. Виявлено 20 569 точних повторів; їх видалено до розбиття, оскільки повторні однакові рядки могли б штучно полегшити оцінювання."),
    ("correlation_matrix.png", "Кореляції ознак", "Кореляційна матриця показує залежності між обсягом переданих даних, кількістю пакетів та іншими числовими характеристиками. Для дерева корельовані ознаки не потребують масштабування, однак лінійна модель масштабує їх і використовує як простий порівняльний метод."),
    ("outlier_boxplots.png", "Викиди за класами", "Розкид мережевих показників суттєво відрізняється між класами та містить крайні значення. Викиди не видаляються автоматично: вони можуть бути характерною ознакою DoS/DDoS, тому в майбутній моделі потрібні перевірка стійкості та контроль впливу екстремальних значень."),
    ("model_comparison.png", "Порівняння методів", "На груповій відкладеній вибірці Random Forest має найвище F1 атак; Logistic Regression дає вищий recall, але нижчий precision. Сигнатурні правила й Isolation Forest у цій конфігурації пропускають значну частину атак, що підтверджує доцільність контрольованої моделі як основи системи."),
    ("rf_confusion_matrix.png", "Матриця помилок Random Forest", "Матриця помилок показує окремо хибні тривоги й пропущені атаки, а не приховує їх загальним показником accuracy. Перед автоматичним карантином у наступних роботах рішення моделі має містити впевненість і журналюватися, а звільнення пристрою залишається ручним."),
    ("feature_importance.png", "Важливість ознак Random Forest", "Найважливішими стали обсяги байтів і пакетні показники. Це відповідає мережевому характеру ознак, але importance Gini не доводить причинний зв'язок; у ЛР 3 результати слід перевірити на відкладених даних і доповнити аналізом помилок."),
]


def image_cell(filename: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_code_cell(
        "from IPython.display import Image, display\n"
        f"display(Image(filename=str(PROJECT / 'images' / {filename!r}), width=760))"
    )


def build_notebook() -> Path:
    (CODE / "notebooks").mkdir(parents=True, exist_ok=True)
    cells = [
        nbformat.v4.new_markdown_cell(
            "# Первинний аналіз ToN_IoT Network\n\n"
            "Лабораторна робота № 1. Тема: керування віртуальними IoT-пристроями з виявленням вторгнень. "
            "Аналіз відтворюється з `random_state = 42`. Використано лише мережеву підвибірку ToN_IoT; "
            "реальні IoT-пристрої не залучаються."
        ),
        nbformat.v4.new_markdown_cell(
            "## Джерело та межі даних\n\n"
            "Першоджерело ToN_IoT: UNSW Canberra. Власник набору дозволяє його використання для академічних досліджень "
            "із цитуванням публікацій. Завантажено опрацьований мережевий CSV через дзеркало Hugging Face; "
            "аналіз охоплює саме локальний файл і не претендує на опис усіх піднаборів ToN_IoT. "
            "`label` є бінарною міткою, `type` описує сімейство події. IP-адреси застосовуються лише для групового "
            "розбиття, не як предиктори моделі."
        ),
        nbformat.v4.new_code_cell(
            "from pathlib import Path\n"
            "import json, sys\n"
            "import pandas as pd\n"
            "from IPython.display import Image, display\n"
            "candidates = [Path.cwd(), Path.cwd().parent, Path.cwd() / 'code']\n"
            "CODE = next(p for p in candidates if (p / 'src' / 'analysis.py').exists())\n"
            "sys.path.insert(0, str(CODE / 'src'))\n"
            "from analysis import run\n"
            "PROJECT = CODE.parent\n"
            "summary = run()\n"
            "print('Розмір файлу:', summary['rows_loaded'], 'рядків ×', summary['columns'], 'стовпців')\n"
            "print('Після очищення:', summary['rows_after_exact_deduplication'], 'рядків')\n"
            "print('Пропуски:', summary['missing_values'], '| повтори:', summary['exact_duplicates_removed'])\n"
            "print('Перетин src_ip між частинами:', summary['group_overlap'])"
        ),
        nbformat.v4.new_markdown_cell(
            "## Словник ознак\n\n"
            "У файлі 42 вхідні поля та два цільові поля. `src_ip` і `dst_ip` є мережевими ідентифікаторами, "
            "а `label` і `type` є мітками, тому вони не входять до предикторів. Модельний набір використовує 16 "
            "числових ознак трафіку: порти, тривалість, байти й пакети в обох напрямках, пропущені байти, DNS-коди "
            "та кілька HTTP-показників. Решта полів описує протокол/сервіс, DNS-ім'я, TLS, HTTP-запит і повідомлення Zeek."
        ),
    ]
    for filename, title, conclusion in IMAGE_NAMES:
        cells.append(nbformat.v4.new_markdown_cell(f"## {title}\n\n{conclusion}"))
        cells.append(image_cell(filename))

    cells.extend([
        nbformat.v4.new_markdown_cell("## Початкове порівняння методів\n\nРозбиття виконано через StratifiedGroupKFold за `src_ip`: усі записи одного джерела належать лише train або test. Гіперпараметри на цьому етапі не підбираються; значення є попереднім базовим результатом для подальшої перевірки у ЛР 3."),
        nbformat.v4.new_code_cell(
            "metrics = pd.DataFrame(summary['metrics']).T\n"
            "metrics[['accuracy','precision_attack','recall_attack','f1_attack','pr_auc','roc_auc']].round(4)"
        ),
        nbformat.v4.new_markdown_cell(
            "## Попередній висновок\n\n"
            "Random Forest на відкладених джерелах дає найкращий баланс precision і recall у цьому експерименті. "
            "Isolation Forest та прості сигнатури не виявляють достатньої частки атак, а логістична регресія "
            "залишається простим контрольним методом. Ці числа є попередніми: фінальне порівняння, підбір параметрів, "
            "крос-валідація, оцінка хибних тривог і перевірка на зміні розподілу виконуються в лабораторній роботі № 3."
        ),
    ])

    notebook = nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.14"},
        },
    )
    notebook.nbformat = 4
    notebook.nbformat_minor = 5
    nbformat.validate(notebook)
    NOTEBOOK_PATH.write_text(nbformat.writes(notebook), encoding="utf-8")
    return NOTEBOOK_PATH


if __name__ == "__main__":
    path = build_notebook()
    print(path)
