import re

from business_services import (
    get_complaint_summary,
    get_customer_count,
    get_customer_details,
    get_dashboard_metrics,
    get_payments_by_amount_today,
    get_pending_payments,
    get_today_collection,
)


_DASHBOARD_WORDS = (
    "dashboard",
    "snapshot",
    "overview",
    "business status",
    "summary",
    "metrics",
)


def _amount_from_query(query: str) -> float | None:
    q = query.replace(",", "")
    match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)", q, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def classify_business_intent(query: str) -> dict:
    q = query.lower().strip()
    if not q:
        return {"intent": "Other", "entities": {}, "route": None}

    entities = {
        "amount": _amount_from_query(query),
        "date": "today" if "today" in q else None,
        "status": None,
    }
    for status in ("active", "inactive", "pending", "paid", "unpaid", "open"):
        if re.search(r"\b" + status + r"\b", q):
            entities["status"] = status
            break

    # Customer details: show/get/find/details for a named person
    if re.search(r"\b(customer|subscriber|details?|profile|information|info)\b", q) and (
        re.search(r"\b(details?|profile|information|info)\b", q)
        or re.search(r"\b(give|show|get|find|search)\b", q)
    ):
        return {"intent": "Customer Details", "entities": entities, "route": "customer_details"}

    # Payments/invoices for a specific named person (resolved from pronoun)
    if re.search(r"\b(payment|payments|invoice|invoices|bill|bills|due|dues)\b", q) and (
        re.search(r"\b(of|for|by|from)\s+[A-Z][a-z]+", query)
        or re.search(r"\b(his|her|their|this customer|that customer)\b", q)
    ):
        return {"intent": "Customer Details", "entities": entities, "route": "customer_details"}

    if any(word in q for word in _DASHBOARD_WORDS):
        return {"intent": "Dashboard Query", "entities": entities, "route": "dashboard"}

    if (
        ("collection" in q or "collected" in q or "revenue" in q)
        and ("today" in q or "today's" in q)
    ):
        return {"intent": "Collection Query", "entities": entities, "route": "today_collection"}

    if (
        entities.get("amount") is not None
        and "today" in q
        and re.search(r"\b(who|which|paid|payment|payments)\b", q)
    ):
        return {"intent": "Payment Query", "entities": entities, "route": "payments_by_amount_today"}

    if "pending" in q and re.search(r"\b(payment|payments|invoice|invoices|bill|bills)\b", q):
        return {"intent": "Payment Query", "entities": entities, "route": "pending_payments"}

    if re.search(r"\b(how many|count|total|number of)\b", q) and re.search(
        r"\b(customer|customers|subscriber|subscribers)\b", q
    ):
        return {"intent": "Customer Search", "entities": entities, "route": "customer_count"}

    if re.search(r"\b(complaint|complaints|issue|issues)\b", q) and re.search(
        r"\b(how many|count|summary|open|pending|total)\b", q
    ):
        return {"intent": "Complaint Query", "entities": entities, "route": "complaints"}

    return {"intent": "Other", "entities": entities, "route": None}


def route_business_query(query: str, company_id: int | None, scope_label: str) -> dict | None:
    intent = classify_business_intent(query)
    route = intent.get("route")
    entities = intent.get("entities") or {}

    if route == "dashboard":
        return get_dashboard_metrics(company_id, scope_label)
    if route == "customer_details":
        return get_customer_details(company_id, scope_label, query)
    if route == "today_collection":
        return get_today_collection(company_id, scope_label)
    if route == "payments_by_amount_today" and entities.get("amount") is not None:
        return get_payments_by_amount_today(company_id, scope_label, entities["amount"])
    if route == "pending_payments":
        return get_pending_payments(company_id, scope_label)
    if route == "customer_count":
        status = entities.get("status")
        if status in ("paid", "unpaid", "pending", "open"):
            status = None
        return get_customer_count(company_id, scope_label, status=status)
    if route == "complaints":
        return get_complaint_summary(company_id, scope_label)

    return None
