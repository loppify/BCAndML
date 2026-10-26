"""Build a 12-slide Ukrainian project-defense deck from measured figures."""
from __future__ import annotations

import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
IMAGES = ROOT / "images"
OUTPUT = ART / "defense_presentation.pptx"
BLUE = RGBColor(31, 78, 121)
LIGHT = RGBColor(239, 245, 250)
DARK = RGBColor(31, 43, 57)
GREEN = RGBColor(54, 128, 93)
RED = RGBColor(176, 62, 55)
WHITE = RGBColor(255, 255, 255)
GRAY = RGBColor(92, 106, 120)


def text_box(slide, x, y, w, h, text, size=20, color=DARK, bold=False, align=None):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(.06)
    tf.margin_right = Inches(.06)
    tf.margin_top = Inches(.03)
    tf.margin_bottom = Inches(.03)
    for index, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.text = line
        p.font.name = "Aptos"
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = color
        if align is not None:
            p.alignment = align
        p.space_after = Pt(8)
    return shape


def base_slide(prs, title, section="Лабораторна робота 4"):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = WHITE
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(.22))
    bar.fill.solid()
    bar.fill.fore_color.rgb = BLUE
    bar.line.fill.background()
    text_box(slide, .55, .38, 11.9, .55, title, 27, BLUE, True)
    text_box(slide, .6, 7.14, 11.7, .2, f"{section}  |  Тема 28  |  Варіант 14", 9, GRAY)
    return slide


def bullets(slide, items, x=.8, y=1.45, w=11.7, h=5.35, size=20):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(.08)
    for index, item in enumerate(items):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.text = item
        p.level = 0
        p.font.name = "Aptos"
        p.font.size = Pt(size)
        p.font.color.rgb = DARK
        p.space_after = Pt(15)
    return shape


def picture(slide, filename, x, y, w, h):
    path = IMAGES / filename
    slide.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w), height=Inches(h))


def main() -> None:
    summary = json.loads((ART / "lab4_summary.json").read_text(encoding="utf-8"))
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "Експерименти та аналіз результатів IoT IDS"
    prs.core_properties.subject = "Підсумковий захист лабораторного проєкту"
    prs.core_properties.author = "Тарасов Ростислав Максимович"

    # 1. Cover
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = BLUE
    text_box(slide, .9, 1.1, 11.4, .55, "ХНУРЕ  |  Технологія блокчейн та машинне навчання", 17, WHITE)
    text_box(slide, .9, 2.15, 11.7, 1.35, "IoT IDS: експерименти\nта аналіз результатів", 34, WHITE, True)
    text_box(slide, .95, 4.0, 10.8, 1.2,
             "Лабораторна робота № 4\nТема 28  |  Варіант 14", 22, WHITE)
    text_box(slide, .95, 6.05, 10.8, .75,
             "Тарасов Ростислав Максимович  |  ПЗПІ-23-8\nВнесок: 100 %", 16, WHITE)

    # 2. Project architecture
    slide = base_slide(prs, "Проєкт і архітектура")
    bullets(slide, [
        "Завдання: виявити атаку у мережевому потоці й передати перевірене рішення локальному шлюзу.",
        "ToN_IoT -> Python pipeline -> Random Forest -> FastAPI oracle -> DeviceQuarantine.",
        "DeviceRegistry зберігає власника; AccessControl перевіряє тимчасовий дозвіл; DeviceQuarantine фіксує стан і журнал.",
        "Потоки, модель, пояснення та індекс подій залишаються поза EVM у файлах/SQLite; on-chain записуються версія, клас і digest.",
        "Фізичні IoT-пристрої не використовуються. Hardhat і віртуальний gateway утворюють навчальний стенд.",
    ], size=19)

    # 3. Experimental methodology
    slide = base_slide(prs, "Методика вимірювань")
    bullets(slide, [
        "Дані: 211 043 рядки, після точного dedup - 190 474; 16 числових ознак.",
        "Group-aware train/validation/test за src_ip: 36 / 6 / 9 груп, перетин груп дорівнює нулю.",
        "Порівняння: сигнатурні правила, Logistic Regression і Random Forest; seed 42.",
        "Мінімум п'ять повторів: Sepolia, gas buckets, сценарій, шум, обсяг даних та централізований baseline.",
        "Для ML порівняння застосовано paired cluster bootstrap на held-out source groups; лише 9 груп тесту обмежують точність інтервалів.",
        "Sepolia fee/ETH-EUR знято 26.10.2026; всі транзакції були тестнетними.",
    ], size=18)

    # 4. Chain confirmation
    slide = base_slide(prs, "Підтвердження транзакцій")
    picture(slide, "transaction_latency.png", .55, 1.25, 8.4, 5.55)
    bullets(slide, [
        "Hardhat: n=100, середнє 3,81 мс, p95 7,19 мс.",
        "Sepolia: n=5, median 11,26 с, mean 20,66 с, max 47,51 с.",
        "Testnet latency залежить від включення транзакції та RPC polling; це не гарантія фінальності.",
        "Локальна EVM непридатна для прогнозу реальної мережевої затримки.",
    ], x=9.1, y=1.6, w=3.8, h=4.9, size=16)

    # 5. Gas
    slide = base_slide(prs, "Залежність gas від історії")
    picture(slide, "gas_by_prior_records.png", .55, 1.25, 8.2, 5.45)
    bullets(slide, [
        "recordDecision повторено 5 разів при 0, 1, 10 і 100 попередніх записах.",
        "Після першого запису: 118 444-118 468 gas; 10 і 100 записів дають 118 468 gas.",
        "Перший mapping write: 135 568 gas через ініціалізацію storage slot.",
        "Calldata стала: 164 байти. Сирий flow не передається; у контракті зберігається bytes32 digest.",
        "Лінійного зростання gas з історією рішення не виявлено.",
    ], x=8.85, y=1.55, w=4.0, h=5.1, size=16)

    # 6. Load
    slide = base_slide(prs, "Навантаження та вузьке місце")
    picture(slide, "gateway_load.png", .55, 1.35, 8.3, 5.25)
    bullets(slide, [
        "10 / 50 / 100 одночасних users, по 10 перевірок на кожного.",
        "1000 запитів за рівень, помилок і відмов не було.",
        "Throughput: 29,4 / 28,7 / 26,5 request/s.",
        "При 100 users p95 = 4,75 с: вузьке місце - синхронна API-to-RPC перевірка на одному вузлі.",
        "1000 послідовних запитів: p95 = 82,96 мс, що проходить NFR-06 для одиночного режиму.",
    ], x=8.9, y=1.55, w=4.0, h=5.0, size=15)

    # 7. Main scenario and centralized baseline
    slide = base_slide(prs, "Час головного сценарію")
    picture(slide, "scenario_components.png", .55, 1.35, 7.4, 5.3)
    bullets(slide, [
        "Після прогріву виміряно п'ять проходів.",
        "Середні витрати: читання стану 17,2 мс; model 35,3 мс; oracle tx/receipt 95,3 мс; event mirror 89,4 мс.",
        "SQLite writes 5,7 мс, canonicalization/hash 0,23 мс.",
        "Instrumented sum 259,1 мс; окремий HTTP inference mean 207,3 мс.",
        "Централізований ML+SHAP+SQLite baseline: mean 52,1 мс.",
    ], x=8.1, y=1.55, w=4.8, h=5.1, size=16)

    # 8. Statistical model comparison
    slide = base_slide(prs, "Порівняння моделей і невизначеність")
    picture(slide, "paired_model_differences.png", .55, 1.3, 7.3, 5.2)
    bullets(slide, [
        "Random Forest: F1 0,9638; recall 0,9996; precision 0,9305; FPR 0,2484.",
        "Logistic Regression: F1 0,9138; baseline rules: F1 0,0002.",
        "RF - LR paired cluster-bootstrap delta F1 = 0,0429; 95 % CI [0,0005; 0,1971].",
        "CI побудовано за 9 test source groups, тому вона широка; напрямок різниці позитивний, але мала кількість груп обмежує висновок.",
    ], x=7.95, y=1.55, w=4.9, h=5.15, size=16)

    # 9. Robustness and volume
    slide = base_slide(prs, "Стійкість і обсяг навчальних даних")
    picture(slide, "noise_robustness.png", .35, 1.4, 6.3, 4.7)
    picture(slide, "training_volume.png", 6.8, 1.4, 6.15, 4.7)
    text_box(slide, .7, 6.2, 12.0, .62,
             "Gaussian noise 5/10/20 % train SD: RF F1 0,6045 / 0,5458 / 0,4845. Навчання на 20-100 % train дає validation F1 0,9972-0,9976. Синтетичний шум не є моделлю фізичного датчика.", 15, DARK)

    # 10. Security
    slide = base_slide(prs, "Безпека, STRIDE та відмови")
    picture(slide, "security_checks.png", .55, 1.45, 6.3, 4.7)
    bullets(slide, [
        "15/15 практичних checks пройшли: 9 API/data/fault і 6 contract-level атак.",
        "Заблоковано: non-oracle call, неавторизований grant/model registration, confidence 10001, replay hash, write під час pause.",
        "100/100 змінених payload не пройшли SHA-256 integrity.",
        "Oracle outage: HTTP 502, запис має status=failed і помилка видима; повтор можливий з тим самим flow ID.",
        "SQLite outage: HTTP 502 і транзакція не надсилається; durable queue відсутня, caller має зберегти запит для retry.",
        "IPFS у системі не використовується.",
    ], x=6.95, y=1.45, w=5.95, h=5.35, size=15)

    # 11. Cost and literature comparison
    slide = base_slide(prs, "Вартість і порівняння з дослідженнями")
    picture(slide, "monthly_costs.png", .45, 1.4, 7.2, 4.9)
    bullets(slide, [
        "Сценарій: 1000 рішень/день, 30 днів, proxy gas 384 428, fee snapshot 26.10.2026.",
        "Execution-only: Ethereum L1 ~€1188/міс.; Arbitrum ~€480; Optimism ~€24.",
        "L2 totals не дорівнюють execution-only: exact fee залежить від batch data, compression та operator fee.",
        "Централізований VPS €5/міс. є бюджетним припущенням, не котируванням.",
        "Gupta et al. 2025: F1 97,7 %, mean 230 мс; Kouassi et al. 2025: F1 93 %; Qaddos et al. 2024: accuracy 99,60 % / 99,16 % на інших datasets.",
        "Показники не є прямим рейтингом через різні набори, розбиття та testbed.",
    ], x=7.75, y=1.35, w=5.15, h=5.5, size=14)

    # 12. Conclusion and demonstration
    slide = base_slide(prs, "Висновки та демонстрація")
    picture(slide, "nfr_compliance.png", .45, 1.35, 6.25, 5.2)
    bullets(slide, [
        "8 з 9 NFR досягнуті; NFR-03 FPR=0,2484 не досяг цілі 0,05.",
        "NFR-06 проходить у 1000 послідовних lookup, але concurrency test показав p95 4,75 с при 100 users.",
        "Пріоритети: threshold за source groups; більше незалежних temporal groups; асинхронна черга oracle; batch/cache read-only RPC; durable retry/outbox; точна L2 fee оцінка.",
        "Жива демонстрація 5-7 хв: registration -> нормальний потік -> атака/quarantine -> gateway deny -> audit/hash integrity -> результати та обмеження.",
    ], x=6.9, y=1.55, w=5.95, h=5.2, size=16)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUTPUT)
    print(json.dumps({"presentation": str(OUTPUT), "slides": len(prs.slides)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
