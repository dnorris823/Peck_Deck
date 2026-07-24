"""Write the generated OpenAPI schema to a file.

    python scripts/export_openapi.py                 # -> docs/openapi.json
    python scripts/export_openapi.py path/to/out.json

Committing the exported spec makes contract changes show up in review as a diff
— otherwise a route or field can change and nothing in the PR reflects it. The
live schema is always served at /schema/openapi.json; this is a snapshot.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.main import app  # noqa: E402


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "openapi.json"
    dest.parent.mkdir(parents=True, exist_ok=True)

    schema = app.openapi_schema.to_schema()
    dest.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paths = schema.get("paths", {})
    operations = sum(
        1 for methods in paths.values() for m in methods if m.lower() in
        {"get", "post", "put", "delete", "patch"}
    )
    print(f"wrote {dest.relative_to(ROOT)} — {len(paths)} paths, {operations} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
