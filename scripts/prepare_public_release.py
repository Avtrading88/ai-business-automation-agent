import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REMOVE_FILE_PATTERNS = [
    "data/output/*.json",
    "data/output/*.jsonl",
    "data/output/*.csv",
    "data/output/*.xlsx",
    "data/output/*.txt",
    "data/output/*.db",
    "data/output/*.db-journal",
    "logs/*.log",
]

REMOVE_DIRS = [
    "data/output/config_backups",
    "data/output/system_backups",
    "data/output/system_restore_staging",
    "data/output/versioned_runs",
    "data/scheduled_input",
    "data/scheduled_archive",
    "data/scheduled_errors",
]

SENSITIVE_FILES = [
    ".env",
    ".env.dev",
    ".env.prod",
    ".streamlit/secrets.toml",
]


def ensure_gitkeep(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".gitkeep").touch()


def main() -> None:
    print("Preparing public release...")

    removed = []
    for pattern in REMOVE_FILE_PATTERNS:
        for path in ROOT.glob(pattern):
            if path.name == ".gitkeep":
                continue
            path.unlink(missing_ok=True)
            removed.append(str(path.relative_to(ROOT)))

    for rel in REMOVE_DIRS:
        path = ROOT / rel
        if path.exists():
            shutil.rmtree(path)
            removed.append(str(path.relative_to(ROOT)))

    ensure_gitkeep(ROOT / "data/output")
    ensure_gitkeep(ROOT / "data/scheduled_input")
    ensure_gitkeep(ROOT / "data/scheduled_archive")
    ensure_gitkeep(ROOT / "data/scheduled_errors")
    ensure_gitkeep(ROOT / "logs")

    found_sensitive = [rel for rel in SENSITIVE_FILES if (ROOT / rel).exists()]

    print(f"Removed generated/local artifacts: {len(removed)}")
    for item in removed[:50]:
        print(f"- {item}")
    if len(removed) > 50:
        print(f"... and {len(removed) - 50} more")

    if found_sensitive:
        print("\nWARNING: Sensitive local files still exist. Do not commit them:")
        for item in found_sensitive:
            print(f"- {item}")
    else:
        print("\nNo common sensitive local files found.")

    print("\nNext: run git status and review every file before commit.")


if __name__ == "__main__":
    main()
