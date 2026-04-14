"""Service discovery API — query the Supabase service directory."""

import json
import os
import urllib.request
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")


def query_supabase(path: str, params: str = "") -> list[dict]:
    """Query Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += f"?{params}"

    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
    })
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())


def search_services(
    query: str | None = None,
    service_type: str | None = None,
    max_price: float | None = None,
    sort_by: str = "price",
    limit: int = 20,
) -> list[dict]:
    """Search for services in the directory."""
    filters = ["is_active=eq.true"]

    if service_type:
        filters.append(f"service_type=eq.{service_type}")

    if max_price is not None:
        filters.append(f"price=lte.{max_price}")

    if query:
        # Use Supabase text search on description, title, service_type, payment_method, and raw_content
        filters.append(f"or=(title.ilike.%25{quote(query)}%25,description.ilike.%25{quote(query)}%25,service_type.ilike.%25{quote(query)}%25,payment_method.ilike.%25{quote(query)}%25,raw_content.ilike.%25{quote(query)}%25)")

    # Sort
    if sort_by == "price":
        order = "price.asc.nullslast"
    elif sort_by == "newest":
        order = "post_created_at.desc"
    else:
        order = "price.asc.nullslast"

    params = "&".join(filters) + f"&order={order}&limit={limit}"
    return query_supabase("services", params)


def get_service_types() -> list[dict]:
    """Get summary of available service types with counts."""
    # Supabase doesn't support GROUP BY via REST easily
    # So fetch all and aggregate in Python
    services = query_supabase("services", "is_active=eq.true&select=service_type,price,currency")

    type_stats = {}
    for s in services:
        st = s.get("service_type", "other")
        if st not in type_stats:
            type_stats[st] = {"count": 0, "min_price": None, "max_price": None, "currencies": set()}
        type_stats[st]["count"] += 1
        price = s.get("price")
        if price is not None:
            if type_stats[st]["min_price"] is None or price < type_stats[st]["min_price"]:
                type_stats[st]["min_price"] = price
            if type_stats[st]["max_price"] is None or price > type_stats[st]["max_price"]:
                type_stats[st]["max_price"] = price
        currency = s.get("currency")
        if currency:
            type_stats[st]["currencies"].add(currency)

    result = []
    for st, stats in sorted(type_stats.items(), key=lambda x: -x[1]["count"]):
        result.append({
            "service_type": st,
            "count": stats["count"],
            "min_price": stats["min_price"],
            "max_price": stats["max_price"],
            "currencies": list(stats["currencies"]),
        })
    return result
