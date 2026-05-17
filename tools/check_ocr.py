from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from privacy_scan import ocr_available


def main() -> None:
    ok, detail = ocr_available()
    if ok:
        print(f"OCR OK: {detail}")
        return
    print(f"OCR NOT READY: {detail}")
    print("Windows quick install: winget install UB-Mannheim.TesseractOCR")
    print("Then restart the app. If needed, set TESSERACT_CMD in .env to the tesseract.exe path.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
