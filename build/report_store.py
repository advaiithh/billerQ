import html
import time
import uuid
from typing import Any


_REPORT_TTL_SEC = 30 * 60
_REPORTS: dict[str, dict[str, Any]] = {}

SENSITIVE_COLUMN_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "hash",
    "salt",
    "token",
    "secret",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "otp",
    "pin",
    "session",
    "remember",
)


def is_sensitive_column(column: str) -> bool:
    normalized = column.lower().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in SENSITIVE_COLUMN_MARKERS)


def safe_result(columns: list[str], rows: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    keep_indexes = [
        idx for idx, column in enumerate(columns)
        if not is_sensitive_column(str(column))
    ]
    safe_columns = [columns[idx] for idx in keep_indexes]
    safe_rows = [[row[idx] for idx in keep_indexes] for row in rows]
    return safe_columns, safe_rows


def store_report(
    *,
    title: str,
    summary: str,
    columns: list[str],
    rows: list[list[Any]],
    user_id: int | None,
    company_id: int | None,
) -> str:
    cleanup_reports()
    report_id = uuid.uuid4().hex
    safe_columns, safe_rows = safe_result(columns, rows)
    _REPORTS[report_id] = {
        "id": report_id,
        "title": title,
        "summary": summary,
        "columns": safe_columns,
        "rows": safe_rows,
        "user_id": user_id,
        "company_id": company_id,
        "created_at": time.time(),
    }
    return report_id


def get_report(report_id: str) -> dict[str, Any] | None:
    cleanup_reports()
    return _REPORTS.get(report_id)


def cleanup_reports() -> None:
    now = time.time()
    expired = [
        report_id for report_id, report in _REPORTS.items()
        if now - report["created_at"] > _REPORT_TTL_SEC
    ]
    for report_id in expired:
        _REPORTS.pop(report_id, None)


def render_report_html(report: dict[str, Any]) -> str:
    columns = report.get("columns") or []
    rows = report.get("rows") or []
    title = html.escape(str(report.get("title") or "Report"))
    summary = html.escape(str(report.get("summary") or ""))

    header = "".join(f"<th>{html.escape(str(col))}</th>" for col in columns)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(
            f"<td>{html.escape(str(value))}</td>" for value in row
        ) + "</tr>"

    if not rows:
        body = f"<tr><td colspan='{max(len(columns), 1)}'>No rows available.</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Segoe UI, system-ui, sans-serif; background: #0d1117; color: #e6edf3; }}
    header {{ padding: 18px 24px; background: #161b22; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; gap: 16px; align-items: center; }}
    h1 {{ font-size: 18px; margin: 0 0 4px; }}
    p {{ margin: 0; color: #9da7b3; font-size: 13px; }}
    main {{ padding: 22px 24px; }}
    a {{ color: #58a6ff; text-decoration: none; }}
    .note {{ background: #1a2430; border: 1px solid #388bfd; border-radius: 8px; padding: 12px 14px; margin-bottom: 16px; color: #c9d1d9; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #30363d; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ text-align: left; background: #1d2a22; color: #3fb950; padding: 10px 12px; white-space: nowrap; }}
    td {{ padding: 9px 12px; border-top: 1px solid #21262d; white-space: nowrap; color: #c9d1d9; }}
    tr:hover td {{ background: #151b23; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{title}</h1>
      <p>{summary}</p>
    </div>
    <a href="/app">Back to chat</a>
  </header>
  <main>
    <div class="note">Sensitive fields such as passwords, tokens, secrets, credential hashes, OTPs, and API keys are hidden automatically.</div>
    <div class="table-wrap">
      <table>
        <thead><tr>{header}</tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  </main>
</body>
</html>"""
