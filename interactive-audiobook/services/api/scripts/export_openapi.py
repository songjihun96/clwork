"""Write the OpenAPI schema to a file, for TypeScript type generation.

Usage:  python scripts/export_openapi.py openapi.json
Needs no database or Redis: the app factory does not connect at construction time.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.main import create_app


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    settings = Settings(_env_file=None, env="development", enable_api_docs=True)  # type: ignore[call-arg]
    app = create_app(settings, configure_logs=False)
    target.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
