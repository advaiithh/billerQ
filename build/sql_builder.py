def build_select_query(data):

    table = data.get("table")

    columns = data.get("columns", ["*"])

    filters = data.get("filters", [])

    sort_by = data.get("sort_by")

    sort_order = data.get(
        "sort_order",
        "DESC"
    )

    limit = data.get("limit", 20)

    sql = f"""
SELECT {", ".join(columns)}
FROM {table}
"""

    # WHERE
    if filters:

        where_parts = []

        for f in filters:

            col = f["column"]

            op = f.get("operator", "=")

            val = f["value"]

            where_parts.append(
                f"{col} {op} '{val}'"
            )

        sql += "\nWHERE " + " AND ".join(where_parts)

    # ORDER BY
    if sort_by:

        sql += f"""
        
ORDER BY {sort_by} {sort_order}
"""

    # LIMIT
    sql += f"""

LIMIT {limit}
"""

    return sql.strip()