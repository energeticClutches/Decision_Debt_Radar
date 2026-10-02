"""Helper for revision scripts: run a SQL file from database/sql/."""

from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def run_sql_file(name: str) -> None:
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    # exec_driver_sql avoids SQLAlchemy bind-parameter parsing of ':' in the SQL.
    # psycopg treats '%' as a placeholder marker, so literal percent signs (format(), RAISE) are doubled.
    op.get_bind().exec_driver_sql(sql.replace("%", "%%"))
