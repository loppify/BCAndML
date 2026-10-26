"""Render the Lab 3 architecture diagrams from Graphviz source files."""
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("components_lab3", "sequence_integration", "database_schema")


def main() -> None:
    dot = shutil.which("dot")
    neato = shutil.which("neato")
    if dot is None or neato is None:
        raise SystemExit("Graphviz is required. Install Graphviz and make `dot` available on PATH.")
    images = ROOT.parent / "images"
    images.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        source = ROOT / "diagrams" / f"{name}.dot"
        output = images / f"{name}.png"
        renderer = [neato, "-n2"] if name == "sequence_integration" else [dot]
        subprocess.run([*renderer, "-Tpng", str(source), "-o", str(output)], check=True)
        print(output)


if __name__ == "__main__":
    main()
