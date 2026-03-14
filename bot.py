import feedparser
import requests
import re
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os

# ── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN         = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID        = os.environ["TELEGRAM_CHANNEL_ID"]
POSTED_FILE       = "posted_ids.json"
MAX_POSTS_PER_RUN = 8    # max articles posted per run
LOOKBACK_HOURS    = 25   # slightly over 24h to avoid missing articles at boundaries

RSS_FEEDS = [

    # ── 🗞️ MAJOR TECH NEWS ────────────────────────────────────────────────
    {"name": "TechCrunch AI",            "url": "https://techcrunch.com/tag/artificial-intelligence/feed/"},
    {"name": "The Verge AI",             "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml"},
    {"name": "Wired AI",                 "url": "https://www.wired.com/feed/tag/ai/latest/rss"},
    {"name": "Ars Technica",             "url": "https://feeds.arstechnica.com/arstechnica/index"},
    {"name": "VentureBeat AI",           "url": "https://venturebeat.com/category/ai/feed/"},
    {"name": "MIT Tech Review",          "url": "https://www.technologyreview.com/feed/"},
    {"name": "The Guardian AI",          "url": "https://www.theguardian.com/technology/artificialintelligenceai/rss"},
    {"name": "New York Times AI",        "url": "https://www.nytimes.com/svc/collections/v1/publish/https://www.nytimes.com/spotlight/artificial-intelligence/rss.xml"},
    {"name": "AI News",                  "url": "https://www.artificialintelligence-news.com/feed/rss/"},
    {"name": "AI Business",              "url": "https://aibusiness.com/rss.xml"},
    {"name": "Futurism AI",              "url": "https://futurism.com/categories/ai-artificial-intelligence/feed"},
    {"name": "404 Media",                "url": "https://www.404media.co/rss"},
    {"name": "KnowTechie AI",            "url": "https://knowtechie.com/category/ai/feed/"},

    # ── 🔬 RESEARCH LABS & OFFICIAL BLOGS ────────────────────────────────
    {"name": "OpenAI Blog",              "url": "https://openai.com/blog/rss.xml"},
    {"name": "OpenAI News",              "url": "https://openai.com/news/rss.xml"},
    {"name": "Google DeepMind",          "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "Google AI Blog",           "url": "https://research.google/blog/rss"},
    {"name": "Apple ML Blog",            "url": "https://machinelearning.apple.com/rss.xml"},
    {"name": "BAIR Berkeley AI",         "url": "https://bair.berkeley.edu/blog/feed.xml"},
    {"name": "MIT News AI",              "url": "https://news.mit.edu/topic/artificial-intelligence2/feed"},
    {"name": "Anthropic Blog",           "url": "https://www.anthropic.com/rss/news.xml"},
    {"name": "Meta AI Blog",             "url": "https://ai.meta.com/blog/feed/"},
    {"name": "Microsoft AI Blog",        "url": "https://blogs.microsoft.com/ai/feed/"},

    # ── 📄 RESEARCH PAPERS ───────────────────────────────────────────────
    {"name": "ArXiv CS.AI",              "url": "https://arxiv.org/rss/cs.AI"},
    {"name": "ArXiv ML",                 "url": "https://arxiv.org/rss/cs.LG"},

    # ── 💡 EXPERT ANALYSIS & NEWSLETTERS ─────────────────────────────────
    {"name": "Ahead of AI",              "url": "https://magazine.sebastianraschka.com/feed"},
    {"name": "AI Accelerator Inst",      "url": "https://aiacceleratorinstitute.com/rss/"},
    {"name": "AI TechPark",              "url": "https://ai-techpark.com/category/ai/feed/"},
    {"name": "ML Mastery",               "url": "https://machinelearningmastery.com/blog/feed"},
    {"name": "The Conversation AI",      "url": "https://theconversation.com/europe/topics/artificial-intelligence-ai-90/articles.atom"},

    # ── 🌐 COMMUNITY & SOCIAL ─────────────────────────────────────────────
    {"name": "Reddit r/artificial",      "url": "https://www.reddit.com/r/artificial/.rss"},
    {"name": "Reddit r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/.rss"},
    {"name": "Hacker News AI",           "url": "https://hnrss.org/newest?q=AI+artificial+intelligence&points=50"},

]
# ────────────────────────────────────────────────────────────────────────────

EMOJI_MAP = {
    "openai":      "🤖",
    "google":      "🔍",
    "apple":       "🍎",
    "deepmind":    "🧠",
    "anthropic":   "🌟",
    "meta":        "🌐",
    "microsoft":   "💻",
    "arxiv":       "📄",
    "mit":         "🎓",
    "bair":        "🔬",
    "reddit":      "💬",
    "hacker":      "👾",
    "wired":       "⚡",
    "guardian":    "📰",
    "venturebeat": "💼",
    "techcrunch":  "🚀",
    "verge":       "📱",
}

def get_emoji(source_name):
    lower = source_name.lower()
    for key, emoji in EMOJI_MAP.items():
        if key in lower:
            return emoji
    return "🤖"


def load_posted_ids():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_posted_ids(ids):
    # Keep only the last 2000 IDs to prevent the file growing forever
    id_list = list(ids)[-2000:]
    with open(POSTED_FILE, "w") as f:
        json.dump(id_list, f)


def get_article_id(entry):
    key = entry.get("link") or entry.get("id") or entry.get("title", "")
    return hashlib.md5(key.encode()).hexdigest()


def is_recent(entry, hours=LOOKBACK_HOURS):
    for attr in ("published_parsed", "updated_parsed"):
        t = entry.get(attr)
        if t:
            try:
                pub = datetime(*t[:6], tzinfo=timezone.utc)
                return datetime.now(timezone.utc) - pub < timedelta(hours=hours)
            except Exception:
                pass
    return True  # no date → include it


def clean_html(text):
    """Strip HTML tags and decode common HTML entities."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def escape_markdown(text):
    """Escape Telegram MarkdownV1 special characters."""
    # Only escape * and _ which break Markdown rendering
    return text.replace("*", r"\*").replace("_", r"\_")


def fetch_articles():
    articles = []
    failed   = []
    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            if feed.bozo and not feed.entries:
                raise ValueError(feed.bozo_exception)
            count = 0
            for entry in feed.entries:
                if is_recent(entry):
                    summary = clean_html(entry.get("summary", ""))[:280]
                    articles.append({
                        "id":      get_article_id(entry),
                        "source":  feed_info["name"],
                        "title":   clean_html(entry.get("title", "No Title")),
                        "link":    entry.get("link", ""),
                        "summary": summary,
                    })
                    count += 1
            print(f"  ✅ {feed_info['name']:<30} → {count} new article(s)")
        except Exception as e:
            failed.append(feed_info["name"])
            print(f"  ❌ {feed_info['name']:<30} → FAILED: {str(e)[:60]}")

    if failed:
        print(f"\n⚠️  {len(failed)}/{len(RSS_FEEDS)} feeds failed: {', '.join(failed)}")
    return articles


def build_message(article):
    emoji   = get_emoji(article["source"])
    title   = escape_markdown(article["title"])
    source  = article["source"]
    summary = article["summary"]
    link    = article["link"]

    summary_block = f"\n\n📄 _{escape_markdown(summary)}..._" if summary else ""

    return (
        f"{emoji} *{source}*\n\n"
        f"*{title}*"
        f"{summary_block}\n\n"
        f"🔗 [Read more]({link})"
    )


def send_to_telegram(article):
    text = build_message(article)
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id":                  CHANNEL_ID,
            "text":                     text,
            "parse_mode":               "Markdown",
            "disable_web_page_preview": False,
        }, timeout=10)
        if resp.status_code != 200:
            print(f"    ⚠️  Telegram error {resp.status_code}: {resp.text[:100]}")
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"    ⚠️  Request error: {e}")
        return False


def main():
    print(f"🚀 AI News Bot — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'─' * 55}")

    posted_ids = load_posted_ids()
    print(f"📂 Previously posted: {len(posted_ids)} articles")
    print(f"🌐 Fetching from {len(RSS_FEEDS)} sources...\n")

    articles    = fetch_articles()
    new_articles = [a for a in articles if a["id"] not in posted_ids]

    print(f"\n{'─' * 55}")
    print(f"📰 New articles found: {len(new_articles)}")

    if not new_articles:
        print("✅ Nothing new to post. Exiting.")
        return

    print(f"📤 Posting up to {MAX_POSTS_PER_RUN} articles...\n")
    posted_count = 0

    for article in new_articles:
        if posted_count >= MAX_POSTS_PER_RUN:
            print(f"🛑 Reached limit of {MAX_POSTS_PER_RUN} posts. Rest will post next run.")
            break
        if send_to_telegram(article):
            posted_ids.add(article["id"])
            posted_count += 1
            print(f"  ✅ Posted: [{article['source']}] {article['title'][:55]}")
        else:
            print(f"  ❌ Failed: [{article['source']}] {article['title'][:55]}")

    save_posted_ids(posted_ids)
    print(f"\n{'─' * 55}")
    print(f"✅ Done — posted {posted_count} article(s)")


if __name__ == "__main__":
    main()
