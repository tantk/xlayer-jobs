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

SUBMOLTS = ["agents", "agentfinance", "builds"]
POSTS_PER_PAGE = 20

GEMMA_MODEL = "gemma-3-12b-it"
GEMMA_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMMA_MODEL}:generateContent?key={GOOGLE_AI_KEY}"

EXTRACTION_PROMPT = """You are extracting structured service listings from Moltbook posts.
Each post is from an AI agent. Some posts offer services, some don't.

For each post, determine if it's offering a service. If yes, extract:
- service_type: one of [code_review, data_analysis, research, image_generation, translation, web_scraping, security_audit, smart_contract, trading_signals, general_ai, other]
- description: one sentence summary of what they offer
- price: numeric price per request/job (null if not stated)
- currency: USDT, USDC, USD, NEAR, credits, or null
- payment_method: one of [x402, dm, api, escrow, platform, unknown]
- endpoint_url: API URL if provided, null otherwise

If the post is NOT offering a service (it's a discussion, opinion, question), return null for that post.

Return a JSON array with one entry per post. Each entry is either null (not a service) or an object with the fields above.

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

        # Process in batches of 20 (to fit in Gemma context)
        batch_size = 20
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

            time.sleep(5)  # Gemma free tier: 15 req/min → 1 batch every 4s + margin

    print(f"\nDone. Processed {total_posts} posts, found {total_services} services.")
    return total_posts, total_services


if __name__ == "__main__":
    crawl_and_extract()
