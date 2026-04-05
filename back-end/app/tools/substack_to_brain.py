"""Convert Substack post summaries into Signa brain knowledge entries.

Usage:
  # After running substack_importer with --summarize:
  python -m app.tools.substack_to_brain --input data/substack/marcelolopez_posts.json

  # This reads the AI summaries and generates brain-ready knowledge entries
  # that can be seeded into the signal_knowledge table.
"""

import argparse
import json
from pathlib import Path

from loguru import logger


def extract_knowledge_entries(posts: list[dict], author: str = "Marcelo Lopez") -> list[dict]:
    """Extract brain knowledge entries from AI-summarized posts."""
    entries = []
    seen_tickers = set()
    seen_sectors = set()
    theses = []

    for post in posts:
        summary = post.get("ai_summary")
        if not summary:
            continue

        # Collect unique tickers and sectors
        for t in summary.get("tickers", []):
            seen_tickers.add(t)
        for s in summary.get("sectors", []):
            seen_sectors.add(s)

        # Collect high-relevance theses
        if summary.get("relevance_to_signa") in ("high", "medium"):
            theses.append({
                "title": post["title"],
                "thesis": summary.get("thesis", ""),
                "tickers": summary.get("tickers", []),
                "sectors": summary.get("sectors", []),
                "insights": summary.get("actionable_insights", []),
                "contrarian": summary.get("contrarian_views", []),
                "sentiment": summary.get("sentiment", "neutral"),
                "date": post.get("date", ""),
                "url": post.get("url", ""),
            })

    # Generate knowledge entries from aggregated insights

    # 1. Sector-level entries
    sector_insights = {}
    for thesis in theses:
        for sector in thesis["sectors"]:
            if sector not in sector_insights:
                sector_insights[sector] = []
            sector_insights[sector].append(thesis)

    for sector, sector_theses in sector_insights.items():
        insights = []
        for t in sector_theses:
            insights.extend(t.get("insights", []))
        contrarian = []
        for t in sector_theses:
            contrarian.extend(t.get("contrarian", []))

        if insights:
            entry = {
                "topic": "SECTOR_ANALYSIS",
                "key_concept": f"lopez_{sector.lower().replace(' ', '_')}_thesis",
                "explanation": f"Marcelo Lopez thesis on {sector}: " + " ".join(insights[:5]),
                "source_name": f"{author} / L2 Capital",
                "source_url": sector_theses[0].get("url", ""),
                "is_active": True,
            }
            if contrarian:
                entry["notes"] = "Contrarian views: " + "; ".join(contrarian[:3])
            entries.append(entry)

    # 2. Aggregate contrarian views
    all_contrarian = []
    for t in theses:
        all_contrarian.extend(t.get("contrarian", []))
    if all_contrarian:
        entries.append({
            "topic": "INSTITUTIONAL_EDGE",
            "key_concept": "lopez_contrarian_framework",
            "explanation": f"Key contrarian views from {author} (L2 Capital, ~30% annual returns): " + " | ".join(list(set(all_contrarian))[:10]),
            "source_name": f"{author} / L2 Capital",
            "source_url": theses[0].get("url", "") if theses else "",
            "is_active": True,
            "notes": f"Based on analysis of {len(theses)} high-relevance posts",
        })

    # 3. Ticker-specific entries for frequently mentioned stocks
    ticker_count = {}
    ticker_sentiment = {}
    for t in theses:
        for ticker in t.get("tickers", []):
            ticker_count[ticker] = ticker_count.get(ticker, 0) + 1
            if ticker not in ticker_sentiment:
                ticker_sentiment[ticker] = []
            ticker_sentiment[ticker].append(t.get("sentiment", "neutral"))

    for ticker, count in sorted(ticker_count.items(), key=lambda x: -x[1]):
        if count >= 2:  # Only tickers mentioned 2+ times
            sentiments = ticker_sentiment[ticker]
            dominant = max(set(sentiments), key=sentiments.count)
            entries.append({
                "topic": "TICKER_THESIS",
                "key_concept": f"lopez_{ticker.lower().replace('.', '_').replace('-', '_')}_view",
                "explanation": f"{author} mentions {ticker} in {count} posts with predominantly {dominant} sentiment.",
                "source_name": f"{author} / L2 Capital",
                "is_active": True,
                "notes": f"Mentioned in {count} posts. Sentiments: {', '.join(sentiments)}",
            })

    return entries


def main():
    parser = argparse.ArgumentParser(description="Convert Substack posts to brain knowledge")
    parser.add_argument("--input", required=True, help="Path to substack_posts.json")
    parser.add_argument("--output", default=None, help="Output JSON for brain entries")
    parser.add_argument("--seed", action="store_true", help="Directly seed into Supabase")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    with open(input_path) as f:
        posts = json.load(f)

    logger.info(f"Loaded {len(posts)} posts")
    entries = extract_knowledge_entries(posts)
    logger.info(f"Generated {len(entries)} brain knowledge entries")

    # Save output
    output_path = Path(args.output) if args.output else input_path.with_name("brain_entries.json")
    with open(output_path, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved to {output_path}")

    # Optionally seed directly
    if args.seed:
        from app.db.supabase import get_client
        client = get_client()
        for entry in entries:
            try:
                client.table("signal_knowledge").upsert(entry, on_conflict="key_concept").execute()
            except Exception as e:
                logger.error(f"Failed to seed {entry['key_concept']}: {e}")
        logger.info(f"Seeded {len(entries)} entries into signal_knowledge")

    # Print summary
    topics = {}
    for e in entries:
        t = e["topic"]
        topics[t] = topics.get(t, 0) + 1

    print(f"\n{'='*50}")
    print(f"BRAIN ENTRIES GENERATED")
    print(f"{'='*50}")
    print(f"Total entries:  {len(entries)}")
    for topic, count in sorted(topics.items()):
        print(f"  {topic}: {count}")
    print(f"Output: {output_path}")
    if args.seed:
        print(f"Seeded to Supabase: YES")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
