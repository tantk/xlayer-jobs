"""Crawl Moltbook submolts and extract service listings using Gemma."""

import json
import os
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MOLTBOOK_API_KEY = os.environ.get("MOLTBOOK_API_KEY", "")
GOOGLE_AI_KEY = os.environ.get("GOOGLE_AI_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")

SUBMOLTS = [
    "agents", "agentfinance", "builds",
    "agentcommerce", "x402", "jobs", "buildlogs",
    "builders", "aitools", "crypto", "technology",
    "infrastructure", "tooling", "buildx",
]
POSTS_PER_PAGE = 20

GEMMA_MODEL = "gemma-3-12b-it"
GEMMA_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMMA_MODEL}:generateContent?key={GOOGLE_AI_KEY}"

EXTRACTION_PROMPT = """Extract ONLY real service offerings from these Moltbook posts.

STRICT RULES:
1. A post is a service ONLY if ALL of these are true:
   - The author BUILT the service themselves (not reporting on someone else's)
   - The service EXISTS and is USABLE right now (not planned, not "coming soon")
   - Another agent could USE the service today (there's an endpoint, API, or clear way to access it)
   - The post is primarily OFFERING the service, not just mentioning it in a story
2. Return null for: opinions, discussions, news, questions, status updates ("I earned $X"), stories ("I ordered a t-shirt"), protocol announcements ("join our protocol"), build logs that don't offer a service, and posts ABOUT services/x402/payments (discussing the concept is NOT offering a service).
3. Price must be the ACTUAL listed price per request/job. Not revenue earned, not hypothetical amounts, not investment amounts. If no price is clearly stated for the service, set price to null. Never set negative prices.
4. service_type must be SPECIFIC. Use "other" only as last resort. Pick the most precise match:
   - code_review: reviews code, PRs, audits codebases
   - data_analysis: analyzes data, provides analytics, on-chain analysis
   - research: researches topics, gathers information, writes reports
   - image_generation: generates images, videos, visual content
   - translation: translates text between languages
   - web_scraping: scrapes websites, extracts web data
   - security_audit: audits smart contracts, scans for vulnerabilities
   - smart_contract: deploys/builds/manages smart contracts
   - trading_signals: provides trading signals, market analysis, price alerts
   - memory_storage: stores/retrieves agent memory or data
   - payment_service: facilitates payments, invoicing, financial operations
   - automation: automates workflows, tasks, processes
   - api_gateway: provides access to external APIs/data sources
5. payment_method: how the buyer actually pays
   - x402: HTTP 402 payment protocol (agent sends request, gets 402, pays crypto, gets response)
   - api_key: traditional API key access (may involve payment separately)
   - dm: contact via DM to arrange payment
   - platform: pay through a specific platform (NEAR Market, ClawGig, etc)
   - crypto_direct: send crypto to an address
   - free: no payment required
   - unknown: cannot determine
6. endpoint_url: ONLY include if a real working URL is provided (starts with http). Not GitHub repos, not documentation links.

EXAMPLES of null (NOT a service):
- "I just ordered a t-shirt using x402" → null (using a service, not offering one)
- "x402 is the future of agent payments" → null (opinion)
- "I earned $500 this week from my API" → null (status update)
- "Join our protocol for on-chain income" → null (recruitment, not a service)
- "Here's what I learned building an x402 service" → null (story/lesson)

EXAMPLES of a service:
- "POST /api/review — send code, get review back. $0.10 per request" → service
- "My scraping API is live at https://... — $0.05/page" → service
- "Offering free security scans for agent skills" → service

For each post, return null if NOT a service, or:
{"service_type": "...", "description": "one sentence of what they sell", "price": number_or_null, "currency": "USDT"|"USDC"|"USD"|"NEAR"|null, "payment_method": "...", "endpoint_url": "..."|null}

Return a JSON array with exactly one entry per post.

Posts:
"""


def fetch_moltbook_posts(submolt: str, cursor: str | None = None, limit: int = POSTS_PER_PAGE) -> tuple[list[dict], str | None]:
    """Fetch posts from a Moltbook submolt. Returns (posts, next_cursor)."""
    url = f"https://www.moltbook.com/api/v1/posts?submolt={submolt}&sort=new&limit={limit}"
    if cursor:
        url += f"&cursor={cursor}"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
    })
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())

    posts = data.get("posts", [])
    next_cursor = data.get("next_cursor") if data.get("has_more") else None
    return posts, next_cursor


def fetch_all_posts(submolt: str, max_pages: int = 50) -> list[dict]:
    """Fetch all posts from a submolt with pagination."""
    all_posts = []
    cursor = None
    for page in range(max_pages):
        posts, cursor = fetch_moltbook_posts(submolt, cursor=cursor)
        if not posts:
            break
        all_posts.extend(posts)
        if not cursor:
            break
        time.sleep(1)  # rate limit: 60 req/min
    return all_posts


def extract_services_with_gemma(posts: list[dict]) -> list[dict | None]:
    """Send batch of posts to Gemma for service extraction."""
    # Build the prompt with post summaries
    post_texts = []
    for i, p in enumerate(posts):
        author = p.get("author", {}).get("name", "unknown")
        title = p.get("title", "")
        content = p.get("content", "")[:500]  # truncate long posts
        post_texts.append(f"[Post {i}] by {author}: {title}\n{content}")

    full_prompt = EXTRACTION_PROMPT + "\n\n".join(post_texts) + "\n\nJSON array:"

    body = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
        },
    }).encode()

    req = urllib.request.Request(GEMMA_URL, data=body, headers={
        "Content-Type": "application/json",
    }, method="POST")

    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())

    # Extract the JSON from Gemma's response
    text = result["candidates"][0]["content"]["parts"][0]["text"]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return [None] * len(posts)


def upsert_services(services: list[dict]):
    """Upsert extracted services to Supabase."""
    if not services:
        return 0

    body = json.dumps(services).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/services?on_conflict=post_id",
        data=body,
        headers={
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return resp.status


def crawl_and_extract(max_pages_per_submolt: int = 50):
    """Main crawl pipeline: fetch posts → extract with Gemma → store in Supabase."""
    total_posts = 0
    total_services = 0

    for submolt in SUBMOLTS:
        print(f"\nCrawling m/{submolt}...")
        posts = fetch_all_posts(submolt, max_pages=max_pages_per_submolt)
        print(f"  Fetched {len(posts)} posts")
        total_posts += len(posts)

        if not posts:
            continue

        # Process in batches of 100 (fits in Gemma 32k context: ~13k tokens per 100 posts)
        batch_size = 100
        for i in range(0, len(posts), batch_size):
            batch = posts[i:i + batch_size]
            print(f"  Processing batch {i // batch_size + 1} ({len(batch)} posts)...")

            try:
                extractions = extract_services_with_gemma(batch)
            except Exception as e:
                print(f"  Gemma error: {e}")
                continue

            # Build service records for non-null extractions
            service_records = []
            for j, extraction in enumerate(extractions):
                if extraction is None:
                    continue
                post = batch[j] if j < len(batch) else None
                if not post:
                    continue

                record = {
                    "post_id": post.get("id", ""),
                    "agent_name": post.get("author", {}).get("name", "unknown"),
                    "agent_id": post.get("author", {}).get("id", ""),
                    "title": post.get("title", ""),
                    "service_type": extraction.get("service_type", "other"),
                    "description": extraction.get("description", ""),
                    "price": extraction.get("price"),
                    "currency": extraction.get("currency"),
                    "payment_method": extraction.get("payment_method", "unknown"),
                    "endpoint_url": extraction.get("endpoint_url"),
                    "submolt": submolt,
                    "source_url": f"https://www.moltbook.com/post/{post.get('id', '')}",
                    "raw_content": post.get("content", "")[:1000],
                    "post_created_at": post.get("created_at"),
                }
                service_records.append(record)

            if service_records:
                try:
                    upsert_services(service_records)
                    total_services += len(service_records)
                    print(f"  Stored {len(service_records)} services")
                except Exception as e:
                    print(f"  Supabase error: {e}")

            time.sleep(60)  # 1 req/min. 120 batches × 60s = 2 hours for full crawl.

    print(f"\nDone. Processed {total_posts} posts, found {total_services} services.")
    return total_posts, total_services


def search_and_extract():
    """Use Moltbook semantic search to find service posts across all submolts."""
    queries = [
        "x402 paid API endpoint service",
        "offering code review service for agents",
        "paid data analysis API",
        "agent service for hire available",
        "built shipped API endpoint pay per request",
        "web scraping service agents",
        "security audit service smart contract",
        "image generation translation service",
        "trading signals paid service",
        "offering research service agents",
    ]

    total_services = 0
    seen_ids = set()

    for query in queries:
        print(f"\nSearching: {query}...")
        url = f"https://www.moltbook.com/api/v1/search?q={urllib.parse.quote(query)}&type=posts&limit=50"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
        })
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())
        except Exception as e:
            print(f"  Search error: {e}")
            continue

        results = data.get("results", [])
        # Filter to unseen posts
        posts = []
        for r in results:
            post_id = r.get("id", r.get("post_id", ""))
            if post_id and post_id not in seen_ids:
                seen_ids.add(post_id)
                # Convert search result format to post format
                posts.append({
                    "id": post_id,
                    "author": r.get("author", {}),
                    "title": r.get("title", "").replace("<mark>", "").replace("</mark>", ""),
                    "content": r.get("content", "").replace("<mark>", "").replace("</mark>", ""),
                    "created_at": r.get("created_at"),
                })

        if not posts:
            print(f"  No new posts")
            continue

        print(f"  {len(posts)} new posts found")

        try:
            extractions = extract_services_with_gemma(posts)
        except Exception as e:
            print(f"  Gemma error: {e}")
            time.sleep(60)
            continue

        records = []
        for i, extraction in enumerate(extractions):
            if extraction is None:
                continue
            post = posts[i] if i < len(posts) else None
            if not post:
                continue

            records.append({
                "post_id": post.get("id", ""),
                "agent_name": post.get("author", {}).get("name", "unknown"),
                "agent_id": post.get("author", {}).get("id", ""),
                "title": post.get("title", ""),
                "service_type": extraction.get("service_type", "other"),
                "description": extraction.get("description", ""),
                "price": extraction.get("price"),
                "currency": extraction.get("currency"),
                "payment_method": extraction.get("payment_method", "unknown"),
                "endpoint_url": extraction.get("endpoint_url"),
                "submolt": "search",
                "source_url": f"https://www.moltbook.com/post/{post.get('id', '')}",
                "raw_content": post.get("content", "")[:1000],
                "post_created_at": post.get("created_at"),
            })

        if records:
            try:
                upsert_services(records)
                total_services += len(records)
                print(f"  Stored {len(records)} services")
            except Exception as e:
                print(f"  Supabase error: {e}")

        time.sleep(60)  # 1 req/min

    print(f"\nSearch complete. Found {total_services} services.")
    return total_services


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        search_and_extract()
    else:
        crawl_and_extract()
