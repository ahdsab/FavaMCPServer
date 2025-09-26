# beancount_income_mcp.py
from fastapi import FastAPI, HTTPException, Query
from fastapi_mcp import FastApiMCP
from typing import Optional, Dict, Any, List
import os
import logging
import requests

# ----------------------- Config & Logging -----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("beancount-income-mcp")

FAVA_BASE_URL = os.getenv("FAVA_BASE_URL", "http://127.0.0.1:5000")
# usually matches the beancount file "slug" in the URL path
FAVA_LEDGER_SLUG = os.getenv("FAVA_LEDGER_SLUG", "example-beancount-file")

# Example endpoint we will call:
#   GET {FAVA_BASE_URL}/{FAVA_LEDGER_SLUG}/api/income_statement
# Optional query params typically include: time, interval, conversion, filter
FAVA_INCOME_API = f"{FAVA_BASE_URL.rstrip('/')}/{FAVA_LEDGER_SLUG}/api/income_statement"

# ----------------------- FastAPI + MCP --------------------------
app = FastAPI(title="Beancount Income Statement MCP")
mcp = FastApiMCP(app)

# ----------------------- Helpers --------------------------------
def _http_get_income_statement(params: Dict[str, Any]) -> Dict[str, Any]:
    """Call Fava's income_statement JSON endpoint and return JSON."""
    try:
        resp = requests.get(FAVA_INCOME_API, params=params, timeout=15)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Fava returned {resp.status_code}")
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.exception("Error calling Fava income_statement")
        raise HTTPException(status_code=502, detail=f"Failed to reach Fava: {str(e)}")


def _num(x: Any) -> Optional[float]:
    try:
        # Some schemas use decimals/strings; be liberal.
        return float(x)
    except Exception:
        return None


def _summarize_income_statement(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Try to craft a human-friendly summary from Fava's income_statement JSON.
    Fava does not guarantee schema stability, so we defensively search for
    likely fields (e.g., totals, income/expenses lists, per-interval series).
    If we can't confidently parse, we still return the raw JSON.
    """
    summary: Dict[str, Any] = {"notes": [], "totals": {}, "top_income": [], "top_expenses": []}

    # Heuristics for common shapes seen in Fava chart APIs:
    # 1) { "totals": {"income": x, "expenses": y, "net": z}, "children":[...categories...] }
    # 2) { "income": {...}, "expenses": {...}, "net_profit": number, ... }
    # 3) Nested "account" trees with "balance" or "amount" fields.
    totals_candidates = [
        ("totals", "income"),
        ("totals", "expenses"),
        ("totals", "net"),
        ("income",),
        ("expenses",),
        ("net_profit",),
        ("net",),
    ]

    # Try to locate totals
    income_total = None
    expenses_total = None
    net_total = None

    if isinstance(data.get("totals"), dict):
        income_total = _num(data["totals"].get("income"))
        expenses_total = _num(data["totals"].get("expenses"))
        net_total = _num(data["totals"].get("net") or data["totals"].get("profit") or data["totals"].get("net_profit"))

    if income_total is None:
        income_total = _num(data.get("income"))
    if expenses_total is None:
        expenses_total = _num(data.get("expenses"))
    if net_total is None:
        net_total = _num(data.get("net_profit") or data.get("net") or data.get("profit"))

    # Fallback: compute net if we have income & expenses (expenses may be negative)
    if net_total is None and income_total is not None and expenses_total is not None:
        net_total = income_total + expenses_total

    summary["totals"] = {
        "income": income_total,
        "expenses": expenses_total,
        "net_profit": net_total,
    }

    # Collect category breakdown if present
    # Many Fava APIs expose a tree of categories under something like "children" with "name" and "balance"/"amount"
    cats: List[Dict[str, Any]] = []
    def collect_categories(node: Any):
        if isinstance(node, dict):
            name = node.get("name") or node.get("label") or node.get("account") or node.get("title")
            # check common numeric fields
            val = _num(node.get("balance") or node.get("amount") or node.get("value") or node.get("total"))
            if name is not None and val is not None:
                cats.append({"name": str(name), "value": val})
            # recurse children arrays/dicts
            ch = node.get("children") or node.get("accounts") or node.get("items")
            if isinstance(ch, list):
                for c in ch:
                    collect_categories(c)
            elif isinstance(ch, dict):
                collect_categories(ch)
        elif isinstance(node, list):
            for c in node:
                collect_categories(c)

    # attempt typical keys
    for key in ("children", "accounts", "items", "tree", "data"):
        if key in data:
            collect_categories(data[key])

    # Derive top 5 income and expenses (expenses likely negative)
    if cats:
        inc = sorted([c for c in cats if c["value"] is not None and c["value"] > 0], key=lambda x: x["value"], reverse=True)[:5]
        exp = sorted([c for c in cats if c["value"] is not None and c["value"] < 0], key=lambda x: abs(x["value"]), reverse=True)[:5]
        summary["top_income"] = inc
        summary["top_expenses"] = exp

    # Add reading tips
    summary["notes"].append("Income is money in; expenses are money out (often negative).")
    summary["notes"].append("Net Profit ≈ Income + Expenses (if expenses are negative, they reduce profit).")
    summary["notes"].append("Numbers are best-effort parsed; Fava’s API may change between versions.")

    return summary

# ----------------------- Routes / MCP Tools ----------------------

@app.get(
    "/income_statement",
    operation_id="explain_income_statement",
    summary="Fetch & explain Fava income statement",
)
async def explain_income_statement(
    time: Optional[str] = Query(None, description="Time filter, e.g. '2024', '2025-01-01..2025-06-30'"),
    interval: Optional[str] = Query(None, description="e.g. 'month', 'quarter', 'year'"),
    conversion: Optional[str] = Query(None, description="e.g. 'USD', 'units'"),
    filter: Optional[str] = Query(None, description="Fava filter string (account:, tag:, payee:, etc.)"),
    return_raw: bool = Query(True, description="Include raw JSON from Fava"),
):
    """
    Calls Fava's /api/income_statement and returns:
      - summary: beginner-friendly totals + top categories (best effort)
      - raw:     the original JSON (optional)
    """
    params: Dict[str, Any] = {}
    if time: params["time"] = time
    if interval: params["interval"] = interval
    if conversion: params["conversion"] = conversion
    if filter: params["filter"] = filter

    logger.info("Fetching income_statement from Fava: %s params=%s", FAVA_INCOME_API, params)
    data = _http_get_income_statement(params)
    summary = _summarize_income_statement(data)

    result = {"source": FAVA_INCOME_API, "summary": summary}
    if return_raw:
        result["raw"] = data
    return result


# Mount MCP over HTTP (so MCP clients like Copilot/Claude can attach via HTTP transport)
mcp.mount_http()
mcp.setup_server()

# ----------------------- Entrypoint ------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
