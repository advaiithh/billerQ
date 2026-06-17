"""
BillerQ Business Copilot - Services Layer
==========================================
Dashboard-First Architecture: These services are preferred over SQL generation.
Each service encapsulates business logic and provides a clean API.

Usage order (Dashboard-First):
1. Dashboard Cache (pre-fetched metrics)
2. Business Service (API calls to BillerQ admin APIs)
3. Database Query (only if data unavailable from above)

Multi-Tenant Security: All services accept company_id and filter by it.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional, Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# BASE SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class BaseService:
    """Base class for all business services with common API call utilities."""

    def __init__(self, admin_api_base: str, token: Optional[str] = None):
        self.admin_api_base = admin_api_base.rstrip("/")
        self.token = token

    def _get_headers(self, company_id: Optional[int] = None) -> dict:
        """Build headers with auth and multi-tenant support."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if company_id:
            headers["X-Company-Id"] = str(company_id)
        return headers

    async def _get(self, endpoint: str, company_id: Optional[int] = None, params: dict = None) -> dict:
        """Perform GET request to admin API."""
        url = f"{self.admin_api_base}{endpoint}"
        headers = self._get_headers(company_id)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def _format_currency(self, value: Any) -> str:
        """Format value as Indian Rupee."""
        try:
            v = float(value)
            if v >= 10_000_000:
                return f"₹{v / 10_000_000:.2f} Cr"
            elif v >= 100_000:
                return f"₹{v / 100_000:.2f} Lakh"
            elif v >= 1_000:
                return f"₹{v:,.0f}"
            else:
                return f"₹{v:.2f}"
        except (ValueError, TypeError):
            return f"₹{value}"

    def _format_number(self, value: Any) -> str:
        """Format number with commas."""
        try:
            v = int(value)
            return f"{v:,}"
        except (ValueError, TypeError):
            return str(value)

    def _safe_get(self, data: dict, *keys, default=None):
        """Safely traverse nested dict."""
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key, default)
            else:
                return default
        return current


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class DashboardService(BaseService):
    """
    Service for dashboard-level metrics.
    These are the fastest responses - no SQL needed.
    """

    METRICS = {
        "total_customers": {"api": "/admin/get-customer", "field": "total", "label": "Total Customers", "unit": "count"},
        "active_customers": {"api": "/admin/get-customer", "field": "active", "label": "Active Customers", "unit": "count"},
        "inactive_customers": {"api": "/admin/get-customer", "field": "inactive", "label": "Inactive Customers", "unit": "count"},
        "today_collection": {"api": "/admin/dashboard", "field": "today_collection", "label": "Today's Collection", "unit": "currency"},
        "today_payments": {"api": "/admin/dashboard", "field": "today_payments", "label": "Today's Payments", "unit": "count"},
        "pending_amount": {"api": "/admin/dashboard", "field": "pending_amount", "label": "Pending Amount", "unit": "currency"},
        "open_complaints": {"api": "/admin/dashboard", "field": "open_complaints", "label": "Open Complaints", "unit": "count"},
        "active_subscriptions": {"api": "/admin/dashboard", "field": "active_subscriptions", "label": "Active Subscriptions", "unit": "count"},
        "monthly_collection": {"api": "/admin/dashboard", "field": "monthly_collection", "label": "Monthly Collection", "unit": "currency"},
        "total_outstanding": {"api": "/admin/get-payment-due-data", "field": "total", "label": "Total Outstanding", "unit": "currency"},
        "overdue_customers": {"api": "/admin/overdue-list", "field": "total", "label": "Overdue Customers", "unit": "count"},
    }

    async def get_metric(self, metric_key: str, company_id: Optional[int] = None) -> dict:
        """
        Fetch a specific dashboard metric.
        Returns: { value, formatted, label, unit, page }
        """
        if metric_key not in self.METRICS:
            return {"error": f"Unknown metric: {metric_key}"}

        metric = self.METRICS[metric_key]
        try:
            data = await self._get(metric["api"], company_id)
            value = data.get(metric["field"])
            if value is None:
                value = self._safe_get(data, "data", metric["field"])

            if value is not None:
                formatted = self._format_currency(value) if metric["unit"] == "currency" else self._format_number(value)
                return {
                    "value": value,
                    "formatted": formatted,
                    "label": metric["label"],
                    "unit": metric["unit"],
                    "page": metric.get("page", "dashboard"),
                    "source": "dashboard_api",
                }
            return {"error": f"Field '{metric['field']}' not found in API response"}
        except httpx.HTTPStatusError as e:
            logger.error(f"Dashboard API error for {metric_key}: {e}")
            return {"error": f"Dashboard API returned {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.error(f"Dashboard API connection error for {metric_key}: {e}")
            return {"error": "Cannot reach dashboard service"}
        except Exception as e:
            logger.error(f"Unexpected error fetching {metric_key}: {e}")
            return {"error": str(e)}

    async def get_dashboard_summary(self, company_id: Optional[int] = None) -> str:
        """Get a natural language summary of all key dashboard metrics."""
        metrics_data = await asyncio_gather_dict({
            key: self.get_metric(key, company_id)
            for key in ["today_collection", "active_customers", "pending_amount", "open_complaints", "active_subscriptions"]
        })

        parts = []
        if "today_collection" in metrics_data and "error" not in metrics_data["today_collection"]:
            parts.append(f"Today's collection is {metrics_data['today_collection']['formatted']}")
        if "active_customers" in metrics_data and "error" not in metrics_data["active_customers"]:
            parts.append(f"{metrics_data['active_customers']['formatted']} active customers")
        if "pending_amount" in metrics_data and "error" not in metrics_data["pending_amount"]:
            parts.append(f"₹{metrics_data['pending_amount']['value']:,.0f} pending")
        if "open_complaints" in metrics_data and "error" not in metrics_data["open_complaints"]:
            parts.append(f"{metrics_data['open_complaints']['formatted']} open complaints")
        if "active_subscriptions" in metrics_data and "error" not in metrics_data["active_subscriptions"]:
            parts.append(f"{metrics_data['active_subscriptions']['formatted']} active subscriptions")

        if parts:
            return "📊 Dashboard Summary:\n" + "\n".join(f"• {p}" for p in parts)
        return "Unable to fetch dashboard data at this time."


# ═══════════════════════════════════════════════════════════════════════════════
# COLLECTION SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class CollectionService(BaseService):
    """Service for collection-related queries."""

    async def get_today_collection(self, company_id: Optional[int] = None) -> dict:
        """Get today's total collection amount."""
        data = await self._get("/admin/dashboard", company_id)
        value = data.get("today_collection") or self._safe_get(data, "data", "today_collection")
        if value is not None:
            return {
                "value": float(value),
                "formatted": self._format_currency(value),
                "date": date.today().isoformat(),
                "source": "dashboard_api",
            }
        return {"error": "Today's collection data not available"}

    async def get_monthly_collection(self, company_id: Optional[int] = None) -> dict:
        """Get monthly collection total."""
        data = await self._get("/admin/dashboard", company_id)
        value = data.get("monthly_collection") or self._safe_get(data, "data", "monthly_collection")
        if value is not None:
            return {
                "value": float(value),
                "formatted": self._format_currency(value),
                "month": datetime.now().strftime("%B %Y"),
                "source": "dashboard_api",
            }
        return {"error": "Monthly collection data not available"}

    async def get_collections_by_area(self, area: str, company_id: Optional[int] = None) -> dict:
        """Get collection data filtered by area/city."""
        # Uses customer search then aggregates
        try:
            data = await self._get(f"/admin/get-customer", company_id, params={"area": area})
            return {
                "area": area,
                "total_customers": data.get("total", 0),
                "active": data.get("active", 0),
                "source": "customer_api",
            }
        except Exception as e:
            logger.error(f"Area collection error: {e}")
            return {"error": f"Cannot fetch collection data for {area}"}


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class PaymentService(BaseService):
    """Service for payment-related queries."""

    async def get_today_payments(self, company_id: Optional[int] = None) -> dict:
        """Get today's payment count and total."""
        data = await self._get("/admin/dashboard", company_id)
        count = data.get("today_payments") or self._safe_get(data, "data", "today_payments")
        amount = data.get("today_collection") or self._safe_get(data, "data", "today_collection")
        return {
            "count": int(count) if count else 0,
            "amount": float(amount) if amount else 0.0,
            "formatted_amount": self._format_currency(amount) if amount else "₹0",
            "date": date.today().isoformat(),
            "source": "dashboard_api",
        }

    async def get_pending_payments(self, company_id: Optional[int] = None) -> dict:
        """Get pending payment information."""
        data = await self._get("/admin/dashboard", company_id)
        pending = data.get("pending_amount") or self._safe_get(data, "data", "pending_amount")
        if pending is not None:
            return {
                "amount": float(pending),
                "formatted": self._format_currency(pending),
                "source": "dashboard_api",
            }
        # Fallback to payment due data
        try:
            due_data = await self._get("/admin/get-payment-due-data", company_id)
            total = due_data.get("total") or self._safe_get(due_data, "data", "total")
            if total is not None:
                return {
                    "amount": float(total),
                    "formatted": self._format_currency(total),
                    "source": "payment_due_api",
                }
        except Exception:
            pass
        return {"error": "Pending payment data not available"}

    async def get_payments_by_customer(self, customer_name: str, company_id: Optional[int] = None) -> dict:
        """Search payments by customer name."""
        return {
            "customer": customer_name,
            "message": f"Searching payments for {customer_name}. Please check the payment page for details.",
            "page": "/payment/quick-pay",
            "source": "navigation",
        }

    async def get_recent_payments(self, limit: int = 5, company_id: Optional[int] = None) -> dict:
        """Get recent payment transactions."""
        try:
            data = await self._get("/admin/dashboard", company_id)
            return {
                "recent": data.get("recent_payments", []),
                "count": len(data.get("recent_payments", [])),
                "source": "dashboard_api",
            }
        except Exception:
            return {"error": "Recent payment data not available"}


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMER SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class CustomerService(BaseService):
    """Service for customer-related queries."""

    async def search_customers(self, query: str, company_id: Optional[int] = None) -> dict:
        """Search customers by name, phone, or area."""
        criteria = {}
        # Detect search type
        if query.isdigit() and len(query) >= 10:
            criteria["phone"] = query
        elif any(area in query.lower() for area in ["kochi", "ernakulam", "trivandrum", "calicut", "kollam"]):
            criteria["area"] = query
        else:
            criteria["name"] = query

        try:
            data = await self._get("/admin/get-customer", company_id, params=criteria)
            results = data.get("data", data.get("customers", []))
            total = data.get("total", len(results))

            return {
                "query": query,
                "total_found": total,
                "results": results[:10],  # Limit to 10
                "has_more": total > 10,
                "source": "customer_api",
            }
        except Exception as e:
            logger.error(f"Customer search error: {e}")
            return {
                "query": query,
                "error": "Search not available",
                "source": "error",
            }

    async def get_customer_summary(self, company_id: Optional[int] = None) -> dict:
        """Get customer summary counts."""
        data = await self._get("/admin/get-customer", company_id)
        return {
            "total": data.get("total", 0),
            "active": data.get("active", 0),
            "inactive": data.get("inactive", 0),
            "formatted_total": self._format_number(data.get("total", 0)),
            "formatted_active": self._format_number(data.get("active", 0)),
            "formatted_inactive": self._format_number(data.get("inactive", 0)),
            "source": "customer_api",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLAINT SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class ComplaintService(BaseService):
    """Service for complaint-related queries."""

    async def get_open_complaints(self, company_id: Optional[int] = None) -> dict:
        """Get count of open complaints."""
        data = await self._get("/admin/dashboard", company_id)
        count = data.get("open_complaints") or self._safe_get(data, "data", "open_complaints")
        if count is not None:
            return {
                "count": int(count),
                "formatted": self._format_number(count),
                "status": "open",
                "source": "dashboard_api",
            }
        return {"error": "Complaint data not available"}

    async def get_complaints_by_status(self, status: str = "open", company_id: Optional[int] = None) -> dict:
        """Get complaints filtered by status."""
        try:
            data = await self._get("/admin/dashboard", company_id)
            count = data.get(f"{status}_complaints") if status != "open" else data.get("open_complaints")
            return {
                "status": status,
                "count": int(count) if count else 0,
                "source": "dashboard_api",
                "page": "/complaints",
            }
        except Exception:
            return {"error": f"Cannot fetch {status} complaints"}


# ═══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class SubscriptionService(BaseService):
    """Service for subscription-related queries."""

    async def get_active_subscriptions(self, company_id: Optional[int] = None) -> dict:
        """Get count of active subscriptions."""
        data = await self._get("/admin/dashboard", company_id)
        count = data.get("active_subscriptions") or self._safe_get(data, "data", "active_subscriptions")
        if count is not None:
            return {
                "count": int(count),
                "formatted": self._format_number(count),
                "status": "active",
                "source": "dashboard_api",
            }
        return {"error": "Subscription data not available"}

    async def get_subscription_summary(self, company_id: Optional[int] = None) -> dict:
        """Get subscription summary."""
        return {
            "active": (await self.get_active_subscriptions(company_id)).get("count", 0),
            "source": "dashboard_api",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# REVENUE SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class RevenueService(BaseService):
    """Service for revenue-related queries and insights."""

    async def get_total_outstanding(self, company_id: Optional[int] = None) -> dict:
        """Get total outstanding amount."""
        try:
            data = await self._get("/admin/get-payment-due-data", company_id)
            total = data.get("total") or self._safe_get(data, "data", "total")
            if total is not None:
                return {
                    "amount": float(total),
                    "formatted": self._format_currency(total),
                    "source": "payment_due_api",
                }
        except Exception:
            pass
        return {"error": "Outstanding data not available"}

    async def get_revenue_summary(self, company_id: Optional[int] = None) -> dict:
        """Get revenue summary combining multiple sources."""
        dashboard = await self._get("/admin/dashboard", company_id)
        return {
            "today_collection": self._format_currency(dashboard.get("today_collection", 0)),
            "monthly_collection": self._format_currency(dashboard.get("monthly_collection", 0)),
            "pending_amount": self._format_currency(dashboard.get("pending_amount", 0)),
            "source": "dashboard_api",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class ReportService(BaseService):
    """Service for report generation and summaries."""

    REPORT_TYPES = {
        "daily": {
            "label": "Daily Report",
            "description": "Today's collections, payments, new customers, and complaints",
            "endpoint": "/admin/dashboard",
        },
        "collection": {
            "label": "Collection Report",
            "description": "Collection metrics including today, monthly, and pending amounts",
            "endpoint": "/admin/dashboard",
        },
        "customer": {
            "label": "Customer Report",
            "description": "Customer statistics including active, inactive, and new customers",
            "endpoint": "/admin/get-customer",
        },
        "payment": {
            "label": "Payment Report",
            "description": "Payment status, due amounts, and overdue customers",
            "endpoint": "/admin/get-payment-due-data",
        },
    }

    async def generate_report(self, report_type: str, company_id: Optional[int] = None) -> dict:
        """Generate a report based on type."""
        report_config = self.REPORT_TYPES.get(report_type)
        if not report_config:
            return {"error": f"Unknown report type: {report_type}"}

        try:
            data = await self._get(report_config["endpoint"], company_id)
            return {
                "type": report_type,
                "label": report_config["label"],
                "description": report_config["description"],
                "data": data,
                "generated_at": datetime.now().isoformat(),
                "source": "report_service",
            }
        except Exception as e:
            logger.error(f"Report generation error: {e}")
            return {"error": f"Could not generate {report_type} report"}


# ═══════════════════════════════════════════════════════════════════════════════
# SERVICE FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

class ServiceFactory:
    """Factory to create and cache service instances."""

    def __init__(self, admin_api_base: str):
        self.admin_api_base = admin_api_base
        self._services = {}

    def get_dashboard(self, token: Optional[str] = None) -> DashboardService:
        return DashboardService(self.admin_api_base, token)

    def get_collection(self, token: Optional[str] = None) -> CollectionService:
        return CollectionService(self.admin_api_base, token)

    def get_payment(self, token: Optional[str] = None) -> PaymentService:
        return PaymentService(self.admin_api_base, token)

    def get_customer(self, token: Optional[str] = None) -> CustomerService:
        return CustomerService(self.admin_api_base, token)

    def get_complaint(self, token: Optional[str] = None) -> ComplaintService:
        return ComplaintService(self.admin_api_base, token)

    def get_subscription(self, token: Optional[str] = None) -> SubscriptionService:
        return SubscriptionService(self.admin_api_base, token)

    def get_revenue(self, token: Optional[str] = None) -> RevenueService:
        return RevenueService(self.admin_api_base, token)

    def get_report(self, token: Optional[str] = None) -> ReportService:
        return ReportService(self.admin_api_base, token)


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY: Async gather for dict
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio


async def asyncio_gather_dict(coros: dict):
    """
    Execute multiple coroutines in parallel and return results as dict.
    Usage: results = await asyncio_gather_dict({ 'key': service.method() })
    """
    async def task(key, coro):
        try:
            return key, await coro
        except Exception as e:
            return key, {"error": str(e)}

    tasks = [task(key, coro) for key, coro in coros.items()]
    results = await asyncio.gather(*tasks)
    return dict(results)