"""Create the database and dump a human-readable DDL reference to schema.sql.

Run: python -m db.export_schema
"""

from pathlib import Path

from sqlalchemy.schema import CreateTable

from db.session import Base, engine, init_db


def export_ddl() -> str:
    lines = []
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(engine)).strip() + ";")
    return "\n\n".join(lines) + "\n"


def main() -> None:
    init_db()
    ddl = export_ddl()
    out = Path(__file__).resolve().parent / "schema.sql"
    out.write_text(ddl, encoding="utf-8")
    print(f"Initialized database and wrote DDL to {out}")


if __name__ == "__main__":
    main()
