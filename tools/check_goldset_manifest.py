from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the synthetic frozen-eval fixture manifest.")
    parser.add_argument("--manifest", type=Path, default=Path("tests/fixtures/goldset_manifest.json"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    base_dir = args.manifest.parent
    failures: list[str] = []
    for item in manifest.get("files", []):
        relative_path = item.get("path", "")
        expected_sha = item.get("sha256", "")
        path = (base_dir / relative_path).resolve()
        if not path.exists():
            failures.append(f"Missing fixture: {relative_path}")
            continue
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            failures.append(f"Checksum mismatch for {relative_path}: {actual_sha} != {expected_sha}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        raise SystemExit(1)
    print(f"Goldset manifest OK: {args.manifest}")


if __name__ == "__main__":
    main()
