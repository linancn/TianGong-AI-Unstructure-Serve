import argparse
import json
import pickle
from pathlib import Path
from typing import Any

DEFAULT_PICKLE_DIR = Path("pickle")


def _load_pickle(path: Path) -> Any:
    with path.open("rb") as handle:
        return pickle.load(handle)


def _resolve_pickle_path(path: Path | None) -> Path:
    if path:
        return path.expanduser()

    newest = _find_newest_pickle(DEFAULT_PICKLE_DIR)
    if not newest:
        raise SystemExit(
            f"No pickle file provided and none found under {DEFAULT_PICKLE_DIR.resolve()}"
        )
    print(f"No pickle_path given, using newest pickle: {newest}")
    return newest


def _find_newest_pickle(directory: Path) -> Path | None:
    if not directory.exists():
        return None
    candidates = sorted(
        directory.glob("*.pkl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _serialize(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump a pickle file to JSON for easier inspection."
    )
    parser.add_argument(
        "pickle_path",
        type=Path,
        nargs="?",
        help="Path to the .pkl file (defaults to the newest file under ./pickle)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional output path (defaults to the same stem with .json suffix)",
    )
    parser.add_argument(
        "--field",
        help="Optional top-level key to extract before dumping (e.g. result)",
    )
    args = parser.parse_args()

    pickle_path = _resolve_pickle_path(args.pickle_path)
    data = _load_pickle(pickle_path)
    if args.field:
        try:
            data = data[args.field]  # type: ignore[index]
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"Unable to extract field '{args.field}': {exc}")

    output_path = (args.output or pickle_path.with_suffix(".json")).expanduser()
    output_path.write_text(_serialize(data), encoding="utf-8")
    print(f"Wrote JSON to {output_path}")


if __name__ == "__main__":
    main()
