"""Substack post importer — fetches and extracts investment insights.

Usage:
  # Step 1: Export your Substack cookies from browser
  # In Chrome: open marcelolopez.substack.com → DevTools → Application → Cookies
  # Copy the 'substack.sid' cookie value

  # Step 2: Run the importer
  cd back-end
  python -m app.tools.substack_importer --author marcelolopez --cookie "YOUR_SUBSTACK_SID"

  # Step 3 (optional): Summarize with AI
  python -m app.tools.substack_importer --author marcelolopez --cookie "YOUR_SID" --summarize

  # Output: JSON file at data/substack/marcelolopez_posts.json
  # Each post has: title, subtitle, date, url, content (full text), summary (if --summarize)
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx
from loguru import logger


SUBSTACK_API = "https://{author}.substack.com/api/v1"
OUTPUT_DIR = Path("data/substack")


def fetch_post_list(author: str, cookie: str = "", limit: int = 200) -> list[dict]:
    """Fetch all posts from a Substack publication."""
    url = f"https://{author}.substack.com/api/v1/archive"
    headers = {}
    if cookie:
        headers["Cookie"] = f"substack.sid={cookie}"

    posts = []
    offset = 0
    batch_size = 12

    while offset < limit:
        params = {"sort": "new", "offset": offset, "limit": batch_size}
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            posts.extend(batch)
            offset += len(batch)
            logger.info(f"Fetched {len(posts)} posts...")
            time.sleep(1)  # Rate limit
        except Exception as e:
            logger.error(f"Failed to fetch posts at offset {offset}: {e}")
            break

    return posts


def fetch_post_content(slug: str, author: str, cookie: str = "") -> str | None:
    """Fetch full post content via Substack API (not HTML scraping).

    The API returns the post body as HTML which we convert to plain text.
    """
    url = f"https://{author}.substack.com/api/v1/posts/{slug}"
    headers = {}
    if cookie:
        headers["Cookie"] = f"substack.sid={cookie}"

    try:
        resp = httpx.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            # Try alternate endpoint
            resp = httpx.get(
                f"https://{author}.substack.com/api/v1/posts/{slug}?token=",
                headers=headers, timeout=15,
            )

        resp.raise_for_status()
        data = resp.json()

        # body_html contains the full article HTML
        body_html = data.get("body_html", "")
        if not body_html:
            # Fallback to truncated body
            body_html = data.get("truncated_body_html", "")

        if body_html:
            import re
            # Strip HTML tags for plain text
            clean = re.sub(r'<[^>]+>', ' ', body_html)
            clean = re.sub(r'\s+', ' ', clean).strip()
            # Decode HTML entities
            import html
            clean = html.unescape(clean)
            return clean

        return None
    except Exception as e:
        logger.debug(f"API fetch failed for {slug}, trying HTML fallback: {e}")
        # Fallback: try HTML page with JSON-LD
        try:
            page_url = f"https://{author}.substack.com/p/{slug}"
            resp = httpx.get(page_url, headers=headers, timeout=15, follow_redirects=True)
            import re
            match = re.search(r'"articleBody"\s*:\s*"(.*?)"', resp.text)
            if match:
                text = match.group(1).replace('\\"', '"').replace('\\n', '\n')
                return text[:5000]
        except Exception:
            pass
        return None


def process_posts(author: str, cookie: str = "", fetch_content: bool = True, max_posts: int = 50) -> list[dict]:
    """Fetch and process all posts."""
    raw_posts = fetch_post_list(author, cookie)
    logger.info(f"Found {len(raw_posts)} posts from {author}")

    processed = []
    for i, post in enumerate(raw_posts[:max_posts]):
        entry = {
            "title": post.get("title", ""),
            "subtitle": post.get("subtitle", ""),
            "date": post.get("post_date", ""),
            "url": post.get("canonical_url", ""),
            "slug": post.get("slug", ""),
            "audience": post.get("audience", "everyone"),  # "everyone" or "only_paid"
            "word_count": post.get("wordcount", 0),
            "likes": post.get("reactions", {}).get("❤", 0) if isinstance(post.get("reactions"), dict) else 0,
        }

        # Fetch full content via API for premium posts
        if fetch_content and cookie and entry["slug"]:
            logger.info(f"[{i+1}/{min(len(raw_posts), max_posts)}] Fetching: {entry['title'][:60]}...")
            content = fetch_post_content(entry["slug"], author, cookie)
            entry["content"] = content
            time.sleep(2)  # Be respectful
        else:
            entry["content"] = post.get("body_text", post.get("truncated_body_text", ""))

        processed.append(entry)

    return processed


def save_posts(posts: list[dict], author: str):
    """Save processed posts to JSON file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{author}_posts.json"

    with open(output_file, "w") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"Saved {len(posts)} posts to {output_file}")
    return output_file


def summarize_with_ai(posts: list[dict]) -> list[dict]:
    """Use Gemini to extract investment insights from each post."""
    try:
        from google import genai
        from app.core.config import settings

        if not settings.gemini_api_key:
            logger.warning("No Gemini API key — skipping AI summarization")
            return posts

        client = genai.Client(api_key=settings.gemini_api_key)

        for i, post in enumerate(posts):
            if not post.get("content"):
                continue

            prompt = f"""Analyze this investment article and extract:
1. Key investment thesis (1-2 sentences)
2. Specific tickers or sectors mentioned
3. Risk factors identified
4. Actionable insights for a 5-20 day holding period signal engine
5. Any contrarian views vs mainstream

Title: {post['title']}
Content (first 3000 chars): {post['content'][:3000]}

Return JSON:
{{
  "thesis": "...",
  "tickers": ["TICKER1", "TICKER2"],
  "sectors": ["sector1", "sector2"],
  "risk_factors": ["risk1", "risk2"],
  "actionable_insights": ["insight1", "insight2"],
  "contrarian_views": ["view1"],
  "sentiment": "bullish" | "bearish" | "neutral",
  "relevance_to_signa": "high" | "medium" | "low"
}}"""

            try:
                response = client.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                )
                import re
                text = response.text.strip()
                if text.startswith("```"):
                    text = "\n".join(text.split("\n")[1:-1])
                post["ai_summary"] = json.loads(text)
                logger.info(f"[{i+1}] Summarized: {post['title'][:50]}...")
                time.sleep(4)  # Rate limit for Gemini free tier
            except Exception as e:
                logger.error(f"AI summary failed for {post['title'][:50]}: {e}")
                post["ai_summary"] = None

    except ImportError:
        logger.error("google-genai not installed — cannot summarize")

    return posts


def main():
    parser = argparse.ArgumentParser(description="Import Substack posts for Signa brain")
    parser.add_argument("--author", default="marcelolopez", help="Substack author slug")
    parser.add_argument("--cookie", default="", help="substack.sid cookie for premium content")
    parser.add_argument("--max-posts", type=int, default=50, help="Max posts to fetch")
    parser.add_argument("--no-content", action="store_true", help="Skip fetching full post content")
    parser.add_argument("--summarize", action="store_true", help="Use AI to extract insights")
    parser.add_argument("--output", default=None, help="Output JSON file path")

    args = parser.parse_args()

    logger.info(f"Importing posts from {args.author}.substack.com")
    if args.cookie:
        logger.info("Premium cookie provided — will fetch paid content")
    else:
        logger.info("No cookie — will only get free content previews")

    posts = process_posts(
        author=args.author,
        cookie=args.cookie,
        fetch_content=not args.no_content,
        max_posts=args.max_posts,
    )

    if args.summarize:
        logger.info("Running AI summarization on posts...")
        posts = summarize_with_ai(posts)

    output_file = save_posts(posts, args.author)

    # Print summary
    total = len(posts)
    with_content = sum(1 for p in posts if p.get("content"))
    with_summary = sum(1 for p in posts if p.get("ai_summary"))
    paid = sum(1 for p in posts if p.get("audience") == "only_paid")

    print(f"\n{'='*50}")
    print(f"IMPORT COMPLETE")
    print(f"{'='*50}")
    print(f"Posts fetched:     {total}")
    print(f"With content:      {with_content}")
    print(f"With AI summary:   {with_summary}")
    print(f"Paid posts:        {paid}")
    print(f"Output file:       {output_file}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
