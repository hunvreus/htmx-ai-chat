from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

ROOT = Path(__file__).resolve().parent
STEPS_DIR = ROOT / "steps"


def discover_steps() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for entry in STEPS_DIR.iterdir():
        if not entry.is_dir() or "-" not in entry.name:
            continue
        number = entry.name.split("-", 1)[0]
        if number.isdigit() and (entry / "app.py").exists():
            result[number] = entry
    return dict(sorted(result.items(), key=lambda item: int(item[0])))


def load_app(step_number: str):
    steps = discover_steps()
    if step_number not in steps:
        available = ", ".join(steps.keys())
        raise SystemExit(f"Unknown step '{step_number}'. Available steps: {available}")

    app_path = steps[step_number] / "app.py"
    spec = importlib.util.spec_from_file_location(f"step_{step_number}_app", app_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Failed to load {app_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "app"):
        raise SystemExit(f"{app_path} has no `app` variable")

    return module.app, steps[step_number]


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run a tutorial step")
    parser.add_argument("--step", default="1", help="Step number, e.g. 1, 6, 7")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    app, step_dir = load_app(args.step)
    print(f"Running step {args.step}: {step_dir.name}")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
