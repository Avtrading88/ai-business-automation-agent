from pathlib import Path

import pandas as pd


class DataReader:
    """Read business data from CSV, Excel, or Google Sheets export files."""

    SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

    def read(self, file_path: str | Path) -> pd.DataFrame:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {path.suffix}. " "Use CSV, XLSX, or XLS files."
            )

        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)

        return pd.read_excel(path)
