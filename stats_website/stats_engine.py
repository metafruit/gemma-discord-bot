#!/usr/bin/env python3
"""
Discord / IRC Statistics Generator Engine
Parses Discord message logs and RAG databases to generate classic IRC-style
statistics (mIRCStats / pisg inspired) including top participants, activity
by hour/day, superlatives (Big Numbers), and an interactive User Connection
Network Graph (Relation Map).
"""

import os
import re
import json
import sqlite3
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path
import html_renderer

BASE_DIR = Path(__file__).resolve().parent.parent
STATS_DIR = Path(__file__).resolve().parent
DATA_OUTPUT_PATH = STATS_DIR / "web" / "data.json"
HTML_OUTPUT_PATH = STATS_DIR / "web" / "index.html"

# Alias / username mapping (loaded from local aliases.json or STATS_ALIAS_MAP env if configured)
ALIAS_MAP_FILE = STATS_DIR / "aliases.json"
ALIAS_MAP = {}
if ALIAS_MAP_FILE.exists():
    try:
        ALIAS_MAP = json.loads(ALIAS_MAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        ALIAS_MAP = {}
elif os.environ.get("STATS_ALIAS_MAP"):
    try:
        ALIAS_MAP = json.loads(os.environ["STATS_ALIAS_MAP"])
    except Exception:
        ALIAS_MAP = {}

URL_REGEX = re.compile(r'https?://[^\s<>"]+')
EMOJI_REGEX = re.compile(r'<a?:\w+:\d+>|[\U00010000-\U0010ffff]')
MENTION_REGEX = re.compile(r'<@!?(\d{16,20})>')


def normalize_author(raw_name: str) -> str:
    """Normalizes nicknames, strips discord handles in parentheses, and maps known aliases."""
    if not raw_name:
        return "Unknown"
    clean = raw_name.strip()
    m = re.match(r'^(.*?)\s*\((.*?)\)$', clean)
    if m:
        disp, user = m.group(1).strip(), m.group(2).strip()
        if user.lower() in ALIAS_MAP:
            return ALIAS_MAP[user.lower()]
        if disp.lower() in ALIAS_MAP:
            return ALIAS_MAP[disp.lower()]
        return disp
    if clean.lower() in ALIAS_MAP:
        return ALIAS_MAP[clean.lower()]
    return clean


def parse_all_messages(base_dir: Path):
    """Gathers and deduplicates messages across current_chunk_raw.txt and rag_memory.db."""
    seen = set()
    messages = []

    def add_message(ts_str: str, author_raw: str, content: str):
        author = normalize_author(author_raw)
        content_clean = content.strip()
        if not content_clean or not author:
            return
        
        # Deduplication key
        key = (ts_str, author, content_clean)
        if key in seen:
            return
        seen.add(key)

        try:
            # First try parsing standard YYYY-MM-DD HH:MM
            dt = datetime.strptime(ts_str[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                # Handle ISO format strings like 2026-08-10T23:50:09...
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                # Strip tzinfo to keep naive UTC for clean comparison
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                ts_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return

        messages.append({
            "timestamp": ts_str,
            "dt": dt,
            "author": author,
            "content": content_clean
        })

    # 1. Parse current_chunk_raw.txt
    raw_txt_path = base_dir / "current_chunk_raw.txt"
    if raw_txt_path.exists():
        with open(raw_txt_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                m = re.match(r'^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s+([^:]+):\s+(.*)$', line)
                if m:
                    add_message(m.group(1), m.group(2), m.group(3))

    # 2. Parse rag_memory.db
    db_path = base_dir / "rag_memory.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            # 2a. raw_discord_history
            cur.execute("SELECT content FROM rag_chunks WHERE source='raw_discord_history';")
            for (block,) in cur.fetchall():
                for line in block.split("\n"):
                    line = line.strip()
                    m = re.match(r'^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s+([^:]+):\s+(.*)$', line)
                    if m:
                        add_message(m.group(1), m.group(2), m.group(3))

            # 2b. chat:#general
            cur.execute("SELECT author, timestamp, content FROM rag_chunks WHERE source='chat:#general';")
            for author_raw, ts, content in cur.fetchall():
                if not author_raw:
                    continue
                # Clean prefix [author]: ... if present
                m_c = re.match(r'^\[.*?\]:\s*(.*)$', content)
                content_clean = m_c.group(1) if m_c else content
                add_message(ts, author_raw, content_clean)

            conn.close()
        except Exception as e:
            print(f"Warning reading rag_memory.db: {e}")

    # Sort messages chronologically
    messages.sort(key=lambda m: m["dt"])
    return messages


def compute_statistics(messages):
    """Computes pisg / mIRCStats style statistics, Big Numbers, and relation network."""
    total_messages = len(messages)
    if total_messages == 0:
        return {}

    total_words = 0
    total_chars = 0
    start_dt = messages[0]["dt"]
    end_dt = messages[-1]["dt"]
    timespan_days = max(1, (end_dt - start_dt).days + 1)

    # Aggregations
    hourly_counts = [0] * 24
    day_of_week_counts = [0] * 7  # 0: Mon, 6: Sun
    daily_timeline = defaultdict(int)

    user_stats = defaultdict(lambda: {
        "lines": 0,
        "words": 0,
        "chars": 0,
        "shouts": 0,
        "questions": 0,
        "exclamations": 0,
        "links": 0,
        "emojis": 0,
        "hourly": [0] * 24,
        "days": [0] * 7,
        "quotes": [],
        "first_seen": "9999-99-99 99:99",
        "last_seen": "0000-00-00 00:00"
    })

    for msg in messages:
        u = msg["author"]
        txt = msg["content"]
        dt = msg["dt"]
        ts_str = msg["timestamp"]

        words = txt.split()
        word_count = len(words)
        char_count = len(txt)

        total_words += word_count
        total_chars += char_count

        hourly_counts[dt.hour] += 1
        day_of_week_counts[dt.weekday()] += 1
        daily_timeline[dt.strftime("%Y-%m-%d")] += 1

        st = user_stats[u]
        st["lines"] += 1
        st["words"] += word_count
        st["chars"] += char_count
        st["hourly"][dt.hour] += 1
        st["days"][dt.weekday()] += 1

        if ts_str < st["first_seen"]:
            st["first_seen"] = ts_str
        if ts_str > st["last_seen"]:
            st["last_seen"] = ts_str

        # Superlative / Quirk tracking
        alpha_chars = [c for c in txt if c.isalpha()]
        if len(alpha_chars) >= 5 and (sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)) >= 0.75:
            st["shouts"] += 1

        if "?" in txt:
            st["questions"] += txt.count("?")
        if "!" in txt:
            st["exclamations"] += txt.count("!")

        urls = URL_REGEX.findall(txt)
        if urls:
            st["links"] += len(urls)

        emojis = EMOJI_REGEX.findall(txt)
        if emojis:
            st["emojis"] += len(emojis)

        # Candidate quote selection: clean text, not URL, meaningful length
        clean_quote = txt.strip()
        if (25 <= len(clean_quote) <= 150 and 
            not clean_quote.startswith("http") and 
            not clean_quote.startswith("!") and 
            not clean_quote.startswith("<:") and
            not clean_quote.endswith(".png") and
            not clean_quote.endswith(".jpg")):
            st["quotes"].append(clean_quote)

    # User connection graph (mIRCStats Relation Map)
    # Active users (at least 3 messages)
    active_users = {u for u, st in user_stats.items() if st["lines"] >= 2}
    
    # Precompile regex for name mentions
    mention_patterns = {}
    for u in active_users:
        if len(u) >= 3:
            # Word boundary regex, case insensitive
            mention_patterns[u] = re.compile(r'\b' + re.escape(u.lower()) + r'\b')

    connections = defaultdict(lambda: {"weight": 0, "conversations": 0, "mentions": 0})
    user_pair_interactions = defaultdict(lambda: defaultdict(int))

    # Sliding conversational window (messages within 300 seconds / 5 mins)
    for i in range(len(messages)):
        m1 = messages[i]
        u1 = m1["author"]
        txt1_lower = m1["content"].lower()

        # 1. Mention tracking
        for target_user, pat in mention_patterns.items():
            if target_user != u1 and pat.search(txt1_lower):
                pair = tuple(sorted([u1, target_user]))
                connections[pair]["weight"] += 2
                connections[pair]["mentions"] += 1
                user_pair_interactions[u1][target_user] += 2
                user_pair_interactions[target_user][u1] += 2

        # 2. Conversational Adjacency tracking
        if i < len(messages) - 1:
            m2 = messages[i + 1]
            u2 = m2["author"]
            if u1 != u2 and u1 in active_users and u2 in active_users:
                diff_sec = (m2["dt"] - m1["dt"]).total_seconds()
                if 0 <= diff_sec <= 300:
                    pair = tuple(sorted([u1, u2]))
                    connections[pair]["weight"] += 1
                    connections[pair]["conversations"] += 1
                    user_pair_interactions[u1][u2] += 1
                    user_pair_interactions[u2][u1] += 1

    # Format user leaderboard
    ranked_users = sorted(user_stats.items(), key=lambda x: x[1]["lines"], reverse=True)
    participants = []
    
    # Palette for user clusters/tiers
    tier_colors = [
        "#38bdf8", "#818cf8", "#c084fc", "#f472b6", "#fb7185",
        "#fb923c", "#facc15", "#4ade80", "#34d399", "#2dd4bf"
    ]

    for rank, (uname, st) in enumerate(ranked_users, 1):
        pct = (st["lines"] / total_messages) * 100
        avg_wpl = round(st["words"] / max(1, st["lines"]), 1)
        peak_hr = max(range(24), key=lambda h: st["hourly"][h])
        
        # Pick best quote
        best_quote = ""
        if st["quotes"]:
            # Pick a quote that is nicely representative
            sorted_quotes = sorted(st["quotes"], key=lambda q: (len(q) > 40, len(q)))
            best_quote = sorted_quotes[len(sorted_quotes) // 2]
        
        # Top 5 partners
        top_partners = []
        if uname in user_pair_interactions:
            sorted_partners = sorted(user_pair_interactions[uname].items(), key=lambda x: x[1], reverse=True)[:5]
            top_partners = [{"name": p, "strength": s} for p, s in sorted_partners]

        # Night owl percentage (00:00 to 06:00)
        night_messages = sum(st["hourly"][0:6])
        night_pct = round((night_messages / max(1, st["lines"])) * 100, 1)

        participants.append({
            "rank": rank,
            "name": uname,
            "lines": st["lines"],
            "words": st["words"],
            "chars": st["chars"],
            "percentage": round(pct, 2),
            "avg_words_per_line": avg_wpl,
            "peak_hour": peak_hr,
            "peak_hour_formatted": f"{peak_hr:02d}:00 - {(peak_hr + 1) % 24:02d}:00",
            "night_pct": night_pct,
            "first_seen": st["first_seen"],
            "last_seen": st["last_seen"],
            "best_quote": best_quote,
            "quotes": st["quotes"][:10],
            "hourly": st["hourly"],
            "days": st["days"],
            "top_partners": top_partners,
            "shouts": st["shouts"],
            "questions": st["questions"],
            "exclamations": st["exclamations"],
            "links": st["links"],
            "emojis": st["emojis"]
        })

    # Build Network Graph Nodes and Links
    nodes = []
    links = []

    # Map name to node index/id
    node_id_set = set()
    for p in participants:
        # Include users with >= 3 lines in the network visualization
        if p["lines"] >= 2:
            node_id_set.add(p["name"])
            color_idx = (p["rank"] - 1) % len(tier_colors)
            nodes.append({
                "id": p["name"],
                "label": p["name"],
                "rank": p["rank"],
                "lines": p["lines"],
                "words": p["words"],
                "percentage": p["percentage"],
                "color": tier_colors[color_idx],
                "quote": p["best_quote"],
                "partners_count": len(user_pair_interactions.get(p["name"], {}))
            })

    # Links between valid nodes
    for (u1, u2), cdata in connections.items():
        if u1 in node_id_set and u2 in node_id_set and cdata["weight"] >= 1:
            links.append({
                "source": u1,
                "target": u2,
                "weight": cdata["weight"],
                "conversations": cdata["conversations"],
                "mentions": cdata["mentions"]
            })

    # Sort links by weight descending
    links.sort(key=lambda l: l["weight"], reverse=True)

    # Superlatives / Big Numbers (Classic pisg / mIRCStats Hall of Fame)
    superlatives = []

    # 1. Chatterbox (Most lines)
    if participants:
        top_talker = participants[0]
        superlatives.append({
            "award": "The Chatterbox",
            "icon": "🗣️",
            "user": top_talker["name"],
            "metric": f"{top_talker['lines']:,} lines ({top_talker['percentage']}%)",
            "description": "Never runs out of things to say in the channel."
        })

    # 2. Novelist / Wordsmith (Highest avg words per line, min 25 lines)
    eligible_novelists = [p for p in participants if p["lines"] >= 25]
    if eligible_novelists:
        novelist = max(eligible_novelists, key=lambda p: p["avg_words_per_line"])
        superlatives.append({
            "award": "The Novelist",
            "icon": "📜",
            "user": novelist["name"],
            "metric": f"{novelist['avg_words_per_line']} words/line",
            "description": "Writes comprehensive paragraphs instead of one-liners."
        })

    # 3. The Shouter (Most all-caps lines)
    eligible_shouters = [p for p in participants if p["shouts"] > 0]
    if eligible_shouters:
        shouter = max(eligible_shouters, key=lambda p: p["shouts"])
        superlatives.append({
            "award": "The Loudmouth",
            "icon": "⚡",
            "user": shouter["name"],
            "metric": f"{shouter['shouts']} loud shouts",
            "description": "Cruising with Caps Lock firmly engaged."
        })

    # 4. The Inquisitive (Most question marks)
    eligible_questioners = [p for p in participants if p["questions"] > 0]
    if eligible_questioners:
        questioner = max(eligible_questioners, key=lambda p: p["questions"])
        superlatives.append({
            "award": "The Inquisitive",
            "icon": "❓",
            "user": questioner["name"],
            "metric": f"{questioner['questions']} questions asked",
            "description": "Always seeking answers from the community."
        })

    # 5. Night Owl (Highest % between midnight and 6 AM, min 20 lines)
    eligible_night_owls = [p for p in participants if p["lines"] >= 20 and p["night_pct"] > 0]
    if eligible_night_owls:
        night_owl = max(eligible_night_owls, key=lambda p: p["night_pct"])
        superlatives.append({
            "award": "The Night Owl",
            "icon": "🦉",
            "user": night_owl["name"],
            "metric": f"{night_owl['night_pct']}% of messages late night",
            "description": "Thrives when the rest of the world is sound asleep."
        })

    # 6. Early Bird (Highest % between 6 AM and 12 PM, min 20 lines)
    eligible_early_birds = []
    for p in participants:
        if p["lines"] >= 20:
            morn_pct = round((sum(p["hourly"][6:12]) / p["lines"]) * 100, 1)
            eligible_early_birds.append((p, morn_pct))
    if eligible_early_birds:
        early_bird, morn_val = max(eligible_early_birds, key=lambda x: x[1])
        superlatives.append({
            "award": "The Early Bird",
            "icon": "🌅",
            "user": early_bird["name"],
            "metric": f"{morn_val}% in the morning hours",
            "description": "Greeting the chat bright and early with morning coffee."
        })

    # 7. Linkmaster (Most URLs shared)
    eligible_links = [p for p in participants if p["links"] > 0]
    if eligible_links:
        linkmaster = max(eligible_links, key=lambda p: p["links"])
        superlatives.append({
            "award": "The Linkmaster",
            "icon": "🔗",
            "user": linkmaster["name"],
            "metric": f"{linkmaster['links']} URLs shared",
            "description": "Chief curator of web links, videos, and articles."
        })

    # 8. Emoji Addict (Most custom and unicode emotes)
    eligible_emojis = [p for p in participants if p["emojis"] > 0]
    if eligible_emojis:
        emojier = max(eligible_emojis, key=lambda p: p["emojis"])
        superlatives.append({
            "award": "Emoji Connoisseur",
            "icon": "✨",
            "user": emojier["name"],
            "metric": f"{emojier['emojis']} emotes used",
            "description": "Expresses emotions in colorful pixels and reactions."
        })

    # 9. Social Butterfly (Connected to most unique chatters)
    if participants:
        butterfly = max(participants, key=lambda p: len(p["top_partners"]))
        connected_count = len(user_pair_interactions.get(butterfly["name"], {}))
        superlatives.append({
            "award": "Social Butterfly",
            "icon": "🤝",
            "user": butterfly["name"],
            "metric": f"{connected_count} unique conversation partners",
            "description": "The central bridge connecting different server circles."
        })

    # 10. Dynamic Duo (Strongest mutual connection pair)
    if links:
        top_pair = links[0]
        superlatives.append({
            "award": "Inseparable Duo",
            "icon": "💬",
            "user": f"{top_pair['source']} & {top_pair['target']}",
            "metric": f"{top_pair['weight']} direct interactions",
            "description": "Finishing each other's sentences in the channel."
        })

    # Busiest hour overall
    busiest_hour = max(range(24), key=lambda h: hourly_counts[h])
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    busiest_day_idx = max(range(7), key=lambda d: day_of_week_counts[d])
    busiest_day = day_names[busiest_day_idx]

    # Daily timeline sorted
    daily_timeline_sorted = [
        {"date": d, "count": c} for d, c in sorted(daily_timeline.items())
    ]

    stats_payload = {
        "channel": "#general",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_display": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "period_start": start_dt.strftime("%Y-%m-%d"),
        "period_end": end_dt.strftime("%Y-%m-%d"),
        "timespan_days": timespan_days,
        "overview": {
            "total_messages": total_messages,
            "total_words": total_words,
            "total_chars": total_chars,
            "unique_participants": len(user_stats),
            "avg_messages_per_day": round(total_messages / timespan_days, 1),
            "avg_words_per_message": round(total_words / total_messages, 1),
            "busiest_hour": f"{busiest_hour:02d}:00 - {(busiest_hour + 1) % 24:02d}:00",
            "busiest_day": busiest_day
        },
        "participants": participants,
        "network": {
            "nodes": nodes,
            "links": links
        },
        "hourly_distribution": [
            {
                "hour": h,
                "label": f"{h:02d}:00",
                "count": hourly_counts[h],
                "percentage": round((hourly_counts[h] / total_messages) * 100, 1)
            }
            for h in range(24)
        ],
        "daily_distribution": [
            {
                "day": day_names[d],
                "count": day_of_week_counts[d],
                "percentage": round((day_of_week_counts[d] / total_messages) * 100, 1)
            }
            for d in range(7)
        ],
        "timeline": daily_timeline_sorted,
        "superlatives": superlatives
    }

    return stats_payload


def generate_and_save_data():
    """Extracts data and saves both web/data.json and pre-rendered web/index.html."""
    DATA_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Ingesting logs and RAG chunks...")
    messages = parse_all_messages(BASE_DIR)
    print(f"Loaded {len(messages)} messages. Computing channel statistics...")
    data = compute_statistics(messages)
    
    # 1. Save data.json (for API & programmatic access)
    with open(DATA_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Successfully generated stats: {DATA_OUTPUT_PATH} ({os.path.getsize(DATA_OUTPUT_PATH):,} bytes)")

    # 2. Pre-render 100% complete static HTML (works with zero JS / scripts blocked)
    html_content = html_renderer.render_full_html(data)
    with open(HTML_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Successfully generated pre-rendered static HTML: {HTML_OUTPUT_PATH} ({os.path.getsize(HTML_OUTPUT_PATH):,} bytes)")

    return data


if __name__ == "__main__":
    generate_and_save_data()
