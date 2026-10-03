"""DuckDB-based dataset profiler (ADR-004).

Generates column-level statistics for CSV, JSON, Parquet, and multi-table
datasets without loading the full dataset into RAM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


_FORMAT_READERS = {
    "csv": "read_csv('{path}', AUTO_DETECT=TRUE)",
    "tsv": "read_csv('{path}', DELIM='\\t', AUTO_DETECT=TRUE)",
    "json": "read_json('{path}', AUTO_DETECT=TRUE)",
    "parquet": "read_parquet('{path}')",
}


@dataclass
class ColumnProfile:
    """Statistics for a single column."""
    name: str
    dtype: str
    n_rows: int
    n_nulls: int
    n_distinct: int
    min_val: Any
    max_val: Any
    sample_values: list[Any] = field(default_factory=list)


@dataclass
class TableProfile:
    """Profile for one table / file within the dataset."""
    table_name: str
    file_path: str
    n_rows: int
    n_columns: int
    columns: list[ColumnProfile] = field(default_factory=list)


@dataclass
class DatasetProfile:
    """Aggregate profile for an entire dataset (one or more tables)."""
    owner: str
    slug: str
    total_rows: int
    total_columns: int
    n_tables: int
    tables: list[TableProfile] = field(default_factory=list)
    format: Literal["csv", "tsv", "json", "parquet", "multitable", "unknown"] = "unknown"
    error: str = ""


def profile_file(
    file_path: str,
    fmt: Literal["csv", "tsv", "json", "parquet"],
    table_name: str | None = None,
) -> TableProfile | None:
    """Profile a single file using DuckDB.

    Returns None on error (unsupported format or read failure).
    """
    try:
        import duckdb  # type: ignore[import]
    except ImportError:
        return None

    reader = _FORMAT_READERS.get(fmt)
    if reader is None:
        return None

    reader_expr = reader.replace("{path}", file_path.replace("\\", "/"))
    name = table_name or Path(file_path).stem

    try:
        con = duckdb.connect()
        # Get row count and column names / types
        schema = con.execute(f"DESCRIBE SELECT * FROM {reader_expr}").fetchall()
        n_rows = con.execute(f"SELECT COUNT(*) FROM {reader_expr}").fetchone()[0]  # type: ignore[index]

        columns: list[ColumnProfile] = []
        for col_row in schema:
            col_name = col_row[0]
            col_type = col_row[1]
            # Null count
            n_nulls = con.execute(
                f"SELECT COUNT(*) FROM {reader_expr} WHERE \"{col_name}\" IS NULL"
            ).fetchone()[0]  # type: ignore[index]
            # Distinct count (approximate for large tables)
            n_distinct = con.execute(
                f"SELECT COUNT(DISTINCT \"{col_name}\") FROM {reader_expr}"
            ).fetchone()[0]  # type: ignore[index]
            # Min / max (only for numeric/date-like types)
            try:
                min_val = con.execute(f"SELECT MIN(\"{col_name}\") FROM {reader_expr}").fetchone()[0]  # type: ignore[index]
                max_val = con.execute(f"SELECT MAX(\"{col_name}\") FROM {reader_expr}").fetchone()[0]  # type: ignore[index]
            except Exception:
                min_val = None
                max_val = None
            # Sample 3 non-null values
            try:
                sample_rows = con.execute(
                    f"SELECT \"{col_name}\" FROM {reader_expr} WHERE \"{col_name}\" IS NOT NULL LIMIT 3"
                ).fetchall()
                sample_values = [r[0] for r in sample_rows]
            except Exception:
                sample_values = []

            columns.append(ColumnProfile(
                name=col_name,
                dtype=col_type,
                n_rows=n_rows,
                n_nulls=n_nulls,
                n_distinct=n_distinct,
                min_val=min_val,
                max_val=max_val,
                sample_values=sample_values,
            ))

        con.close()
        return TableProfile(
            table_name=name,
            file_path=file_path,
            n_rows=n_rows,
            n_columns=len(columns),
            columns=columns,
        )
    except Exception as exc:
        return TableProfile(
            table_name=name,
            file_path=file_path,
            n_rows=0,
            n_columns=0,
            columns=[],
        )


def profile_dataset(
    owner: str,
    slug: str,
    raw_dir: str,
) -> DatasetProfile:
    """Profile all files in a dataset's raw directory.

    Scans for CSV, TSV, JSON, and Parquet files and profiles each one.
    Multi-table datasets (multiple files) get one TableProfile per file.

    Parameters
    ----------
    owner, slug:
        Dataset identifier (for metadata only).
    raw_dir:
        Path to the directory containing raw downloaded files.

    Returns
    -------
    DatasetProfile — never raises; errors are captured in DatasetProfile.error.
    """
    raw_path = Path(raw_dir)
    if not raw_path.exists():
        return DatasetProfile(
            owner=owner, slug=slug, total_rows=0, total_columns=0, n_tables=0,
            error=f"raw_dir does not exist: {raw_dir}"
        )

    file_map: dict[str, Literal["csv", "tsv", "json", "parquet"]] = {}
    for f in sorted(raw_path.iterdir()):
        if f.is_file():
            ext = f.suffix.lower().lstrip(".")
            if ext in _FORMAT_READERS:
                file_map[str(f)] = ext  # type: ignore[assignment]

    if not file_map:
        return DatasetProfile(
            owner=owner, slug=slug, total_rows=0, total_columns=0, n_tables=0,
            format="unknown",
            error="No supported tabular files found in raw_dir.",
        )

    tables: list[TableProfile] = []
    for file_path, fmt in file_map.items():
        tp = profile_file(file_path, fmt)
        if tp is not None:
            tables.append(tp)

    total_rows = sum(t.n_rows for t in tables)
    total_cols = sum(t.n_columns for t in tables)

    # Detect overall format
    formats = {file_map[p] for p in file_map}
    if len(tables) > 1:
        fmt_label: Literal["csv", "tsv", "json", "parquet", "multitable", "unknown"] = "multitable"
    elif formats == {"csv"}:
        fmt_label = "csv"
    elif formats == {"tsv"}:
        fmt_label = "tsv"
    elif formats == {"json"}:
        fmt_label = "json"
    elif formats == {"parquet"}:
        fmt_label = "parquet"
    else:
        fmt_label = "unknown"

    return DatasetProfile(
        owner=owner,
        slug=slug,
        total_rows=total_rows,
        total_columns=total_cols,
        n_tables=len(tables),
        tables=tables,
        format=fmt_label,
    )
