from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import urlopen


URL = "https://huggingface.co/datasets/codymlewis/TON_IoT_network/resolve/main/train_test_network.csv"
EXPECTED_SIZE = 29_902_775
EXPECTED_SHA256 = "26ddc513552de36de6428b2e578efaed2b57504c716dfba847cc0109a64e1974"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "ton_iot_network.csv"


def _valid_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size != EXPECTED_SIZE:
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == EXPECTED_SHA256


def download() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if _valid_file(OUTPUT):
        return OUTPUT

    temporary = OUTPUT.with_suffix(".csv.part")
    with urlopen(URL, timeout=90) as response, temporary.open("wb") as destination:
        while chunk := response.read(1024 * 1024):
            destination.write(chunk)

    if temporary.stat().st_size != EXPECTED_SIZE or not _valid_file(temporary):
        actual_size = temporary.stat().st_size
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Dataset integrity check failed: {actual_size} bytes; "
            f"expected {EXPECTED_SIZE} bytes and SHA-256 {EXPECTED_SHA256}."
        )

    temporary.replace(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(download())
