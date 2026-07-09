"""Database migration utility to copy all data from a source database to a destination database.

Discovers all tables at runtime via SQLAlchemy reflection and migrates them in
foreign-key dependency order.

Usage:
    python scripts/migrate_sqlite_to_postgres.py \
        --source sqlite:///./loom.db \
        --dest postgresql+psycopg2://user:pass@host:5432/loom [--skip-existing]
"""
import argparse
from collections import defaultdict
from typing import List

from sqlalchemy import MetaData, create_engine, func, select, text
from sqlalchemy.engine import Engine


def topological_sort(tables: list) -> List:
    """Sort tables so that tables with no FK dependencies come first.

    Uses Kahn's algorithm (BFS-based topological sort).
    """
    table_map = {t.name: t for t in tables}
    in_degree: dict = defaultdict(int)
    dependents: dict = defaultdict(list)

    for table in tables:
        in_degree[table.name]  # ensure key exists
        for fk in table.foreign_keys:
            referred = fk.column.table.name
            if referred != table.name and referred in table_map:
                in_degree[table.name] += 1
                dependents[referred].append(table.name)

    queue = [name for name, deg in in_degree.items() if deg == 0]
    queue.sort()  # deterministic ordering among peers
    sorted_names: List[str] = []

    while queue:
        name = queue.pop(0)
        sorted_names.append(name)
        for dependent in sorted(dependents[name]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # If there are cycles or unresolved tables, append them at the end
    remaining = [name for name in table_map if name not in sorted_names]
    sorted_names.extend(sorted(remaining))

    return [table_map[name] for name in sorted_names]


def migrate(source_url: str, dest_url: str, skip_existing: bool) -> None:
    src_engine: Engine = create_engine(source_url)
    dest_engine: Engine = create_engine(dest_url)

    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)

    dest_meta = MetaData()
    dest_meta.reflect(bind=dest_engine)

    tables = list(src_meta.tables.values())
    ordered_tables = topological_sort(tables)

    total_tables_migrated = 0
    total_rows_copied = 0

    with src_engine.connect() as src_conn:
        with dest_engine.connect() as dest_conn:
            for src_table in ordered_tables:
                table_name = src_table.name

                if table_name not in dest_meta.tables:
                    print(f"SKIPPING {table_name}: table not found in destination")
                    continue

                dest_table = dest_meta.tables[table_name]

                try:
                    if skip_existing:
                        row_count_result = dest_conn.execute(
                            select(func.count()).select_from(dest_table)
                        )
                        existing_count = row_count_result.scalar()
                        if existing_count and existing_count > 0:
                            print(f"Skipping {table_name} (already has data)")
                            continue

                    rows = src_conn.execute(select(src_table)).mappings().all()
                    row_list = [dict(row) for row in rows]

                    if not skip_existing:
                        dest_conn.execute(dest_table.delete())

                    if row_list:
                        dest_conn.execute(dest_table.insert(), row_list)

                    dest_conn.commit()

                    count = len(row_list)
                    print(f"Migrated {table_name}: {count} rows")
                    total_tables_migrated += 1
                    total_rows_copied += count

                except Exception as e:
                    print(f"ERROR {table_name}: {e}")
                    dest_conn.rollback()
                    continue

    print()
    print(f"Migration complete: {total_tables_migrated} tables migrated, {total_rows_copied} rows copied")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate all data from a source database to a destination database."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="SQLAlchemy connection URL for the source database (e.g. sqlite:///./loom.db)",
    )
    parser.add_argument(
        "--dest",
        required=True,
        help="SQLAlchemy connection URL for the destination database (e.g. postgresql+psycopg2://user:pass@host:5432/loom)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="Skip tables in the destination that already contain data",
    )
    args = parser.parse_args()

    migrate(args.source, args.dest, args.skip_existing)


if __name__ == "__main__":
    main()
