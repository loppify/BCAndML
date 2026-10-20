import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts" / "demo-data" / "local-demo-result.json"
OUTPUT = ROOT.parent / "images" / "decision-results.svg"


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    normal = result["demo"]["normal"]
    attack = result["demo"]["attack"]
    width, height = 900, 500
    left, right, top, bottom = 105, 40, 70, 105
    plot_width, plot_height = width - left - right, height - top - bottom
    threshold_y = top + plot_height * (1 - 0.5)
    bars = [
        ("Звичайний потік", normal["confidenceBps"], "#4b8f70", "Active" if normal["onChainStatus"] == 1 else "інший стан"),
        ("Потік атаки", attack["confidenceBps"], "#c94f4f", "Quarantined" if attack["onChainStatus"] == 2 else "інший стан"),
    ]
    bar_width, gap = 170, 110
    start_x = left + (plot_width - (2 * bar_width + gap)) / 2
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="450" y="35" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="22" font-weight="bold">Результати локальної перевірки IoT IDS</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#333" stroke-width="2"/>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{width - right}" y2="{top + plot_height}" stroke="#333" stroke-width="2"/>',
        f'<line x1="{left}" y1="{threshold_y:.1f}" x2="{width - right}" y2="{threshold_y:.1f}" stroke="#d58b28" stroke-width="2" stroke-dasharray="8 6"/>',
        f'<text x="{width - right - 4}" y="{threshold_y - 8:.1f}" text-anchor="end" font-family="DejaVu Sans, sans-serif" font-size="12" fill="#8a5b15">Поріг 50 %</text>',
        f'<text x="30" y="{top + plot_height / 2}" transform="rotate(-90 30 {top + plot_height / 2})" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="15">Впевненість класифікатора, %</text>',
    ]
    for tick in range(0, 10001, 2000):
        y = top + plot_height * (1 - tick / 10000)
        elements.append(f'<line x1="{left - 5}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#ddd" stroke-width="1"/>')
        elements.append(f'<text x="{left - 12}" y="{y + 5:.1f}" text-anchor="end" font-family="DejaVu Sans, sans-serif" font-size="13">{tick / 100:.0f}</text>')
    for index, (label, confidence, color, status) in enumerate(bars):
        x = start_x + index * (bar_width + gap)
        bar_height = plot_height * confidence / 10000
        y = top + plot_height - bar_height
        elements.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" fill="{color}"/>')
        elements.append(f'<text x="{x + bar_width / 2:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="16" font-weight="bold">{confidence / 100:.0f} %</text>')
        elements.append(f'<text x="{x + bar_width / 2:.1f}" y="{top + plot_height + 27}" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="15">{label}</text>')
        elements.append(f'<text x="{x + bar_width / 2:.1f}" y="{top + plot_height + 50}" text-anchor="middle" font-family="DejaVu Sans, sans-serif" font-size="13" fill="#444">Стан: {status}</text>')
    elements.append("</svg>")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(elements) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
