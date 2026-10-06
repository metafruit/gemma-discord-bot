#!/usr/bin/env python3
"""
Server-Side HTML Renderer for IRC / Discord Statistics Dashboard.
Pre-renders all statistics, tables, SVGs, and relationship networks directly into static HTML.
Ensures the page is 100% functional with zero JavaScript (Lynx, w3m, Dillo, or scripts blocked),
while supporting progressive enhancement when scripts are enabled.
"""

import html
import math


def render_top_talkers_svg(participants, limit=15):
    top_list = participants[:limit]
    if not top_list:
        return '<div style="color:#64748b; padding:20px;">No participant data available.</div>'

    max_lines = max(p["lines"] for p in top_list)
    row_height = 36
    height = len(top_list) * row_height + 20

    svg_parts = [
        f'<svg width="100%" height="{height}" viewBox="0 0 800 {height}" preserveAspectRatio="none" style="display:block;">',
        '  <defs>',
        '    <linearGradient id="barGradTop" x1="0%" y1="0%" x2="100%" y2="0%">',
        '      <stop offset="0%" stop-color="#38bdf8"/>',
        '      <stop offset="100%" stop-color="#818cf8"/>',
        '    </linearGradient>',
        '    <linearGradient id="barGradNormal" x1="0%" y1="0%" x2="100%" y2="0%">',
        '      <stop offset="0%" stop-color="#60a5fa"/>',
        '      <stop offset="100%" stop-color="#3b82f6"/>',
        '    </linearGradient>',
        '  </defs>'
    ]

    for idx, user in enumerate(top_list):
        y = idx * row_height + 10
        pct_width = (user["lines"] / max_lines) * 540
        grad = 'url(#barGradTop)' if idx < 3 else 'url(#barGradNormal)'
        uname = html.escape(user["name"])
        disp_name = uname if len(uname) <= 15 else uname[:14] + '…'
        user_anchor = f"#user-{html.escape(user['name'])}"

        svg_parts.append(f'''
          <g class="chart-row">
            <text x="10" y="{y + 18}" fill="#94a3b8" font-size="12" font-family="monospace" font-weight="700">#{user["rank"]}</text>
            <text x="40" y="{y + 18}" fill="#f1f5f9" font-size="13" font-weight="600">{disp_name}</text>
            <rect x="170" y="{y + 6}" width="540" height="16" rx="4" fill="rgba(255,255,255,0.05)" />
            <rect x="170" y="{y + 6}" width="{max(6, pct_width):.1f}" height="16" rx="4" fill="{grad}">
              <title>{uname}: {user["lines"]:,} lines ({user["percentage"]}%)</title>
            </rect>
            <text x="{180 + max(6, pct_width) + 10:.1f}" y="{y + 19}" fill="#cbd5e1" font-size="12" font-family="monospace" font-weight="600">
              {user["lines"]:,} <tspan fill="#64748b">({user["percentage"]}%)</tspan>
            </text>
          </g>
        ''')

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def render_hourly_svg(hourly_data):
    if not hourly_data:
        return ''
    max_count = max(d["count"] for d in hourly_data) or 1
    height = 180
    width = 640
    bar_width = 18
    gap = (width - 40 - (24 * bar_width)) / 23

    svg_parts = [
        f'<svg width="100%" height="{height + 30}" viewBox="0 0 {width} {height + 30}" style="display:block;">'
    ]

    # Grid guide lines
    for i in range(1, 4):
        gy = height - (height * (i / 4))
        svg_parts.append(f'<line x1="30" y1="{gy:.1f}" x2="{width - 10}" y2="{gy:.1f}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3" />')

    for i, d in enumerate(hourly_data):
        x = 35 + i * (bar_width + gap)
        bar_height = max(4, (d["count"] / max_count) * (height - 20))
        y = height - bar_height

        # Daypart color
        if d["hour"] < 6:
            color = "#818cf8"  # Night
        elif d["hour"] < 12:
            color = "#38bdf8"  # Morning
        elif d["hour"] < 18:
            color = "#fbbf24"  # Afternoon
        else:
            color = "#f472b6"  # Evening

        hour_label = f'<text x="{x + bar_width / 2:.1f}" y="{height + 18}" text-anchor="middle" fill="#64748b" font-size="10" font-family="monospace">{d["hour"]:02d}</text>' if i % 2 == 0 else ''

        svg_parts.append(f'''
          <g class="chart-bar-hover">
            <rect x="{x:.1f}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" rx="3" fill="{color}">
              <title>{d["label"]}: {d["count"]:,} messages ({d["percentage"]}%)</title>
            </rect>
            {hour_label}
          </g>
        ''')

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def render_daily_svg(daily_data):
    if not daily_data:
        return ''
    max_count = max(d["count"] for d in daily_data) or 1
    height = 180
    width = 500
    bar_width = 42
    gap = (width - 40 - (7 * bar_width)) / 6

    svg_parts = [
        f'<svg width="100%" height="{height + 30}" viewBox="0 0 {width} {height + 30}" style="display:block;">'
    ]

    for i, d in enumerate(daily_data):
        x = 20 + i * (bar_width + gap)
        bar_height = max(6, (d["count"] / max_count) * (height - 25))
        y = height - bar_height

        svg_parts.append(f'''
          <g class="chart-bar-hover">
            <rect x="{x:.1f}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" rx="4" fill="#38bdf8">
              <title>{d["day"]}: {d["count"]:,} messages ({d["percentage"]}%)</title>
            </rect>
            <text x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" fill="#cbd5e1" font-size="11" font-family="monospace" font-weight="600">{d["percentage"]}%</text>
            <text x="{x + bar_width / 2:.1f}" y="{height + 18}" text-anchor="middle" fill="#94a3b8" font-size="11" font-weight="600">{d["day"][:3]}</text>
          </g>
        ''')

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def render_timeline_svg(timeline_data):
    if not timeline_data:
        return ''
    height = 120
    width = 900
    max_val = max(d["count"] for d in timeline_data) or 10
    step_x = (width - 40) / max(1, len(timeline_data) - 1)

    points = []
    for i, d in enumerate(timeline_data):
        x = 20 + i * step_x
        y = height - 15 - (d["count"] / max_val) * (height - 35)
        points.append(f"{x:.1f},{y:.1f}")

    path_data = "M " + " L ".join(points)
    area_data = f"{path_data} L {20 + (len(timeline_data) - 1) * step_x:.1f},{height - 15} L 20,{height - 15} Z"

    svg_parts = [
        f'<svg width="100%" height="{height + 25}" viewBox="0 0 {width} {height + 25}" style="display:block;">',
        '  <defs>',
        '    <linearGradient id="timelineGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
        '      <stop offset="0%" stop-color="rgba(56, 189, 248, 0.4)"/>',
        '      <stop offset="100%" stop-color="rgba(56, 189, 248, 0.0)"/>',
        '    </linearGradient>',
        '  </defs>',
        f'  <path d="{area_data}" fill="url(#timelineGrad)" />',
        f'  <path d="{path_data}" fill="none" stroke="#38bdf8" stroke-width="2.5" />'
    ]

    step_interval = max(1, len(timeline_data) // 14)
    for i, d in enumerate(timeline_data):
        if i % step_interval == 0 or i == len(timeline_data) - 1:
            x = 20 + i * step_x
            y = height - 15 - (d["count"] / max_val) * (height - 35)
            svg_parts.append(f'''
              <circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#ffffff" stroke="#0284c7" stroke-width="2">
                <title>{d["date"]}: {d["count"]} messages</title>
              </circle>
              <text x="{x:.1f}" y="{height + 14}" text-anchor="middle" fill="#64748b" font-size="10" font-family="monospace">{d["date"][5:]}</text>
            ''')

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def render_static_network_svg(nodes, links, limit_nodes=20):
    """Pre-renders a static SVG Network Graph (mIRCStats Relation Map) for zero-JS browsers."""
    active_nodes = nodes[:limit_nodes]
    if not active_nodes:
        return ''

    width, height = 800, 480
    cx, cy = width / 2, height / 2

    # Map positions in 2 concentric rings
    coords = {}
    node_map = {n["id"]: n for n in active_nodes}
    max_lines = max(n["lines"] for n in active_nodes)

    for i, n in enumerate(active_nodes):
        if i < 6:
            r = 110
            angle = (i / 6) * 2 * math.pi - math.pi / 2
        else:
            r = 195
            angle = ((i - 6) / max(1, len(active_nodes) - 6)) * 2 * math.pi - math.pi / 2
        coords[n["id"]] = (cx + r * math.cos(angle), cy + r * math.sin(angle))

    svg_parts = [
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" style="display:block; background:#0b1120; border-radius:8px;">',
        '  <defs>',
        '    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">',
        '      <feGaussianBlur stdDeviation="3" result="blur" />',
        '      <feComposite in="SourceGraphic" in2="blur" operator="over" />',
        '    </filter>',
        '  </defs>'
    ]

    # Draw connection lines
    drawn_links = 0
    for l in links:
        s, t = l["source"], l["target"]
        if s in coords and t in coords and l["weight"] >= 4:
            x1, y1 = coords[s]
            x2, y2 = coords[t]
            sw = max(1.0, min(6.5, math.sqrt(l["weight"]) * 0.55))
            opacity = min(0.75, 0.2 + (l["weight"] / 150) * 0.55)
            s_esc, t_esc = html.escape(s), html.escape(t)
            svg_parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="#818cf8" stroke-opacity="{opacity:.2f}" stroke-width="{sw:.1f}">'
                f'<title>{s_esc} ↔ {t_esc}: {l["weight"]} interactions ({l["conversations"]} convs, {l["mentions"]} mentions)</title>'
                f'</line>'
            )
            drawn_links += 1

    # Draw nodes
    for n in active_nodes:
        x, y = coords[n["id"]]
        r = max(12, min(32, int(11 + math.sqrt(n["lines"] / max_lines) * 21)))
        col = n.get("color", "#38bdf8")
        uname = html.escape(n["id"])
        rank_str = ['🥇', '🥈', '🥉'][n["rank"] - 1] if n["rank"] <= 3 else f'#{n["rank"]}'

        svg_parts.append(f'''
          <g>
            <circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 3}" fill="rgba(255,255,255,0.08)" />
            <circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}" stroke="#ffffff" stroke-width="1.5">
              <title>{uname} (Rank #{n["rank"]} • {n["lines"]:,} lines)</title>
            </circle>
            <text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" fill="#ffffff" font-size="{max(10, r - 3)}" font-family="monospace" font-weight="700">{rank_str}</text>
            <text x="{x:.1f}" y="{y + r + 14:.1f}" text-anchor="middle" fill="#f1f5f9" font-size="11" font-weight="600">{uname}</text>
          </g>
        ''')

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def render_leaderboard_rows(participants):
    rows = []
    max_lines = participants[0]["lines"] if participants else 1

    for p in participants:
        bar_pct = min(100.0, max(2.5, (p["lines"] / max_lines) * 100))
        rank = p["rank"]

        if rank == 1:
            rank_badge = '<span class="td-rank-badge rank-1">🥇</span>'
        elif rank == 2:
            rank_badge = '<span class="td-rank-badge rank-2">🥈</span>'
        elif rank == 3:
            rank_badge = '<span class="td-rank-badge rank-3">🥉</span>'
        else:
            rank_badge = f'#{rank}'

        uname = html.escape(p["name"])
        quote = html.escape(p["best_quote"]) if p["best_quote"] else "—"
        quote_title = quote if quote != "—" else ""
        quote_display = f'"{quote}"' if quote != "—" else "—"

        rows.append(f'''
          <tr data-username="{uname.lower()}">
            <td class="td-rank">{rank_badge}</td>
            <td class="td-nick"><a href="#user-{uname}" style="color:inherit; font-weight:700;">{uname}</a></td>
            <td style="font-family: monospace; font-weight: 600;">{p["lines"]:,}</td>
            <td>
              <div class="bar-container">
                <div class="bar-track">
                  <div class="bar-fill" style="width: {bar_pct:.1f}%;"></div>
                </div>
              </div>
            </td>
            <td style="font-family: monospace; color: var(--accent-cyan); font-weight: 600;">{p["percentage"]}%</td>
            <td style="font-family: monospace;">{p["words"]:,}</td>
            <td style="font-family: monospace;">{p["avg_words_per_line"]}</td>
            <td style="font-family: monospace; font-size: 0.8rem; color: var(--text-muted);">{p["peak_hour_formatted"]}</td>
            <td class="td-quote" title="{quote_title}">{quote_display}</td>
            <td>
              <a href="#user-{uname}" class="btn-profile" onclick="event.stopPropagation(); window.dispatchEvent(new CustomEvent('open-user-modal', {{detail: '{uname}'}}))">
                Dossier ↗
              </a>
            </td>
          </tr>
        ''')

    return '\n'.join(rows)


def render_relations_table(links, limit=18):
    rows = []
    top_links = links[:limit]
    for i, l in enumerate(top_links, 1):
        s_esc = html.escape(l["source"])
        t_esc = html.escape(l["target"])
        weight = l["weight"]
        convs = l["conversations"]
        mentions = l["mentions"]

        if weight >= 150:
            badge = '<span style="background:rgba(236,72,153,0.2); color:#f472b6; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.75rem;">Inseparable Duo</span>'
        elif weight >= 80:
            badge = '<span style="background:rgba(56,189,248,0.2); color:#38bdf8; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.75rem;">Close Bond</span>'
        else:
            badge = '<span style="background:rgba(129,140,248,0.2); color:#818cf8; padding:2px 8px; border-radius:4px; font-weight:700; font-size:0.75rem;">Frequent Chat</span>'

        rows.append(f'''
          <tr>
            <td style="font-family:monospace; font-weight:700; text-align:center;">#{i}</td>
            <td style="font-weight:700; color:var(--text-main);"><a href="#user-{s_esc}">{s_esc}</a> ↔ <a href="#user-{t_esc}">{t_esc}</a></td>
            <td style="font-family:monospace; font-weight:700; color:var(--accent-gold);">⚡ {weight}</td>
            <td style="font-family:monospace;">{convs}</td>
            <td style="font-family:monospace;">{mentions}</td>
            <td>{badge}</td>
          </tr>
        ''')

    return '\n'.join(rows)


def render_superlatives(superlatives):
    cards = []
    for s in superlatives:
        u_esc = html.escape(s["user"])
        cards.append(f'''
          <div class="award-card">
            <div class="award-top">
              <div class="award-icon">{s["icon"]}</div>
              <div class="award-name">{html.escape(s["award"])}</div>
            </div>
            <div class="award-winner"><a href="#user-{u_esc}" style="color:inherit;">{u_esc}</a></div>
            <div class="award-metric">{html.escape(s["metric"])}</div>
            <div class="award-desc">{html.escape(s["description"])}</div>
          </div>
        ''')
    return '\n'.join(cards)


def render_static_dossiers(participants, limit=20):
    """Pre-renders HTML5 <details> cards for users to browse without JavaScript."""
    dossiers = []
    for p in participants[:limit]:
        uname = html.escape(p["name"])
        lines = p["lines"]
        words = p["words"]
        wpl = p["avg_words_per_line"]
        peak = p["peak_hour_formatted"]
        pct = p["percentage"]
        rank = p["rank"]

        # Partner list HTML
        partners_html = []
        for partner in p.get("top_partners", [])[:4]:
            p_name = html.escape(partner["name"])
            partners_html.append(f'''
              <div class="partner-item" style="display:flex; justify-content:space-between; margin-bottom:4px;">
                <a href="#user-{p_name}" class="partner-name">{p_name}</a>
                <span class="partner-strength">⚡ {partner["strength"]} interactions</span>
              </div>
            ''')
        partners_str = "".join(partners_html) if partners_html else '<div style="color:#64748b;">No conversation partners recorded.</div>'

        # Quotes list HTML
        quotes_html = []
        for q in p.get("quotes", [])[:4]:
            quotes_html.append(f'<div class="quote-bubble" style="margin-bottom:6px;">"{html.escape(q)}"</div>')
        quotes_str = "".join(quotes_html) if quotes_html else '<div style="color:#64748b;">No notable quotes recorded.</div>'

        dossiers.append(f'''
          <details class="member-dossier" id="user-{uname}">
            <summary class="dossier-summary">
              <span class="dossier-rank">#{rank}</span>
              <strong class="dossier-name">{uname}</strong>
              <span class="dossier-meta">{lines:,} lines ({pct}%) • Peak: {peak}</span>
            </summary>
            <div class="dossier-body">
              <div class="modal-stats-grid" style="margin: 12px 0;">
                <div class="mstat-box">
                  <div class="mstat-val">{lines:,}</div>
                  <div class="mstat-lbl">Lines</div>
                </div>
                <div class="mstat-box">
                  <div class="mstat-val">{words:,}</div>
                  <div class="mstat-lbl">Words</div>
                </div>
                <div class="mstat-box">
                  <div class="mstat-val">{wpl}</div>
                  <div class="mstat-lbl">Words/Line</div>
                </div>
                <div class="mstat-box">
                  <div class="mstat-val">{p["peak_hour"]}:00</div>
                  <div class="mstat-lbl">Peak Hour</div>
                </div>
              </div>
              <div style="margin-bottom: 12px;">
                <h4 style="font-size:0.8rem; color:#94a3b8; text-transform:uppercase; margin-bottom:6px;">Top Allies & Chat Partners</h4>
                {partners_str}
              </div>
              <div>
                <h4 style="font-size:0.8rem; color:#94a3b8; text-transform:uppercase; margin-bottom:6px;">Selected Quotes</h4>
                {quotes_str}
              </div>
            </div>
          </details>
        ''')

    return '\n'.join(dossiers)


def render_full_html(data, default_theme="theme-modern"):
    """Generates the full, static, pre-rendered HTML document."""
    overview = data["overview"]
    participants = data["participants"]
    network = data["network"]
    hourly = data["hourly_distribution"]
    daily = data["daily_distribution"]
    timeline = data["timeline"]
    superlatives = data["superlatives"]

    top_talkers_svg = render_top_talkers_svg(participants, limit=15)
    hourly_svg = render_hourly_svg(hourly)
    daily_svg = render_daily_svg(daily)
    timeline_svg = render_timeline_svg(timeline)
    static_network_svg = render_static_network_svg(network["nodes"], network["links"], limit_nodes=20)
    relations_table_html = render_relations_table(network["links"], limit=18)
    leaderboard_rows_html = render_leaderboard_rows(participants)
    superlatives_html = render_superlatives(superlatives)
    dossiers_html = render_static_dossiers(participants, limit=20)

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Channel Statistics — #general (IRC & Discord Stats)</title>
  <link rel="stylesheet" href="style.css">
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body class="{default_theme}">
  <div class="site-wrapper">
    
    <!-- NoScript / Static Mode Banner -->
    <noscript>
      <div class="noscript-banner">
        <span class="noscript-icon">⚡</span>
        <div>
          <strong>Static HTML Mode:</strong> All <strong>{overview["total_messages"]:,} messages</strong>, 
          <strong>{overview["unique_participants"]} participants</strong>, connection maps, charts, and award statistics 
          are 100% pre-rendered server-side. Zero JavaScript or AJAX is required.
        </div>
      </div>
    </noscript>

    <!-- Top Header & Banner -->
    <header class="channel-header">
      <div class="header-top">
        <div class="channel-identity">
          <div class="badge-irc">IRC / DISCORD STATS • ZERO-JS PRE-RENDERED</div>
          <h1 id="channelTitle">Channel Statistics for <span class="highlight-channel">{data["channel"]}</span></h1>
          <p class="subtitle" id="channelMeta">
            Period: <strong>{data["period_start"]}</strong> to <strong>{data["period_end"]}</strong> ({data["timespan_days"]} days) • 
            Generated: <strong>{data.get("generated_display", "Today")}</strong>
          </p>
        </div>
        <div class="header-actions">
          <a href="?theme=retro" id="themeToggleBtn" class="btn btn-secondary" title="Switch Theme (Works with or without JavaScript)">
            <span class="theme-icon">📼</span> <span class="theme-text">Retro IRC Theme</span>
          </a>
          <button id="refreshBtn" class="btn btn-primary" title="Re-scan logs and update stats">
            <span class="refresh-icon">🔄</span> Refresh Stats
          </button>
        </div>
      </div>

      <!-- Quick KPI Strip (Classic pisg / mIRCStats style - Fully Pre-Rendered) -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">TOTAL LINES</div>
          <div class="kpi-value" id="kpiLines">{overview["total_messages"]:,}</div>
          <div class="kpi-sub" id="kpiLinesAvg">{overview["avg_messages_per_day"]} lines/day</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">TOTAL WORDS</div>
          <div class="kpi-value" id="kpiWords">{overview["total_words"]:,}</div>
          <div class="kpi-sub" id="kpiWordsAvg">{overview["avg_words_per_message"]} words/line</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">UNIQUE PARTICIPANTS</div>
          <div class="kpi-value" id="kpiUsers">{overview["unique_participants"]}</div>
          <div class="kpi-sub">Active server members</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">BUSIEST HOUR</div>
          <div class="kpi-value highlight-gold" id="kpiHour">{overview["busiest_hour"].split(' - ')[0]}</div>
          <div class="kpi-sub" id="kpiDay">Peak Day: {overview["busiest_day"]}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">TIME PERIOD</div>
          <div class="kpi-value highlight-cyan" id="kpiDays">{data["timespan_days"]} Days</div>
          <div class="kpi-sub" id="kpiDates">{data["period_start"]} – {data["period_end"]}</div>
        </div>
      </div>
    </header>

    <!-- Navigation Tabs / Section Anchors -->
    <nav class="nav-bar">
      <div class="nav-links">
        <a href="#networkSection" class="nav-item active">🌐 Relation Map (Network)</a>
        <a href="#leaderboardSection" class="nav-item">🏆 Most Active Talkers</a>
        <a href="#activitySection" class="nav-item">⏰ Hourly & Daily Patterns</a>
        <a href="#superlativesSection" class="nav-item">🎖️ Hall of Fame</a>
        <a href="#dossiersSection" class="nav-item">📁 Member Dossiers</a>
      </div>
      <div class="nav-status">
        <span class="status-indicator"></span> 100% Static HTML Ready
      </div>
    </nav>

    <!-- Main Dashboard Content -->
    <main class="dashboard-body">

      <!-- SECTION 1: User Connections & Relation Map -->
      <section id="networkSection" class="dashboard-section">
        <div class="section-header">
          <div>
            <h2><span class="section-icon">🌐</span> User Connections Network Graph</h2>
            <p class="section-desc">
              <strong>mIRCStats Relation Map</strong> — Visualizing conversational bonds and direct mentions. 
              Node size reflects message volume; line thickness reflects interaction strength.
            </p>
          </div>
          <div class="graph-legend">
            <span class="legend-item"><span class="legend-dot rank-top"></span> Top Chatters</span>
            <span class="legend-item"><span class="legend-dot rank-core"></span> Core Members</span>
            <span class="legend-item"><span class="legend-dot rank-casual"></span> Casual Chatters</span>
          </div>
        </div>

        <!-- Dynamic Canvas Interactive Container (Enhanced by JS when available) -->
        <div class="graph-container" id="interactiveCanvasContainer" style="display:none;">
          <div class="graph-toolbar">
            <div class="toolbar-group">
              <label for="minStrengthSlider">Min Connection Strength: <strong id="strengthVal">2</strong></label>
              <input type="range" id="minStrengthSlider" min="1" max="25" value="2" step="1">
            </div>
            <div class="toolbar-group search-group">
              <input type="text" id="graphSearchInput" placeholder="🔍 Highlight member...">
            </div>
            <div class="toolbar-actions">
              <button id="resetGraphBtn" class="tool-btn" title="Reset Camera View">⟲ Reset View</button>
              <button id="togglePhysicsBtn" class="tool-btn" title="Pause/Resume Layout">⏸️ Pause Layout</button>
              <button id="zoomInBtn" class="tool-btn" title="Zoom In">+</button>
              <button id="zoomOutBtn" class="tool-btn" title="Zoom Out">−</button>
            </div>
          </div>
          <div class="canvas-wrapper" id="networkCanvasWrapper">
            <canvas id="networkCanvas"></canvas>
            <div class="graph-tooltip" id="graphTooltip"></div>
            <div class="graph-help-tip">
              💡 <em>Drag nodes • Scroll to zoom • Click any user to view profile</em>
            </div>
          </div>
        </div>

        <!-- Static Fallback Network Diagram (Pre-Rendered SVG, 100% Zero-JS) -->
        <div class="static-network-wrapper" id="staticNetworkWrapper">
          <div class="panel-header-row" style="margin-bottom: 8px;">
            <span class="panel-title">Server Connection Overview (Pre-Rendered SVG Diagram)</span>
            <span style="font-size:0.75rem; color:#94a3b8; font-family:monospace;">Zero Scripts Needed</span>
          </div>
          {static_network_svg}
        </div>

        <!-- Top Interaction Pairs Table (Relation Strength Matrix) -->
        <div style="margin-top: 20px;">
          <h3 style="font-size: 1rem; margin-bottom: 10px; color: var(--text-main);">⚡ Strongest Conversational Bonds (Top Interaction Pairs)</h3>
          <div class="table-responsive">
            <table class="stats-table">
              <thead>
                <tr>
                  <th style="width:40px; text-align:center;">#</th>
                  <th>Member Pair</th>
                  <th>Interaction Score</th>
                  <th>Conversations</th>
                  <th>Direct Mentions</th>
                  <th>Bond Strength</th>
                </tr>
              </thead>
              <tbody>
                {relations_table_html}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- SECTION 2: Most Active Participants -->
      <section id="leaderboardSection" class="dashboard-section">
        <div class="section-header">
          <div>
            <h2><span class="section-icon">🏆</span> Most Active Participants</h2>
            <p class="section-desc">
              Rankings of the most talkative channel members with message counts, conversation shares, words per line, and signature quotes.
            </p>
          </div>
          <div class="table-search-bar">
            <input type="text" id="tableSearchInput" placeholder="🔍 Search participant name...">
          </div>
        </div>

        <!-- Top Talkers Bar Chart (Pre-Rendered SVG) -->
        <div class="chart-panel">
          <div class="panel-title">Top 15 Chatters by Volume</div>
          <div class="custom-chart-wrapper" id="topTalkersChart">
            {top_talkers_svg}
          </div>
        </div>

        <!-- Classic Leaderboard Table (Pre-Rendered HTML) -->
        <div class="table-responsive">
          <table class="stats-table" id="leaderboardTable">
            <thead>
              <tr>
                <th class="th-rank">#</th>
                <th class="th-nick">Nick</th>
                <th class="th-lines">Lines Spoken</th>
                <th class="th-bar">Activity Share</th>
                <th class="th-pct">%</th>
                <th class="th-words">Words</th>
                <th class="th-wpl">Words/Line</th>
                <th class="th-peak">Peak Hour</th>
                <th class="th-quote">Signature Quote</th>
                <th class="th-action">Profile</th>
              </tr>
            </thead>
            <tbody id="leaderboardBody">
              {leaderboard_rows_html}
            </tbody>
          </table>
        </div>
      </section>

      <!-- SECTION 3: Hourly & Daily Activity Patterns -->
      <section id="activitySection" class="dashboard-section">
        <div class="section-header">
          <div>
            <h2><span class="section-icon">⏰</span> Channel Activity Patterns</h2>
            <p class="section-desc">
              24-hour hourly distribution and day-of-week trends showing when the server is most active.
            </p>
          </div>
        </div>

        <div class="charts-dual-grid">
          <!-- 24-Hour Distribution (Pre-Rendered SVG) -->
          <div class="chart-panel">
            <div class="panel-header-row">
              <span class="panel-title">Activity by Hour of the Day (0:00 - 23:00)</span>
              <span class="badge-peak" id="peakHourBadge">Peak: {overview["busiest_hour"].split(' - ')[0]}</span>
            </div>
            <div class="daypart-legend">
              <span class="daypart-tag dp-night">🌙 Night (00-06)</span>
              <span class="daypart-tag dp-morn">🌅 Morning (06-12)</span>
              <span class="daypart-tag dp-after">☀️ Afternoon (12-18)</span>
              <span class="daypart-tag dp-eve">🌆 Evening (18-24)</span>
            </div>
            <div class="custom-chart-wrapper" id="hourlyChart">
              {hourly_svg}
            </div>
          </div>

          <!-- Day of Week Distribution (Pre-Rendered SVG) -->
          <div class="chart-panel">
            <div class="panel-header-row">
              <span class="panel-title">Activity by Day of the Week</span>
              <span class="badge-peak" id="peakDayBadge">Peak: {overview["busiest_day"]}</span>
            </div>
            <div class="custom-chart-wrapper" id="dailyChart">
              {daily_svg}
            </div>
          </div>
        </div>

        <!-- 60-Day Timeline Chart (Pre-Rendered SVG) -->
        <div class="chart-panel timeline-panel">
          <div class="panel-title">Message Volume Timeline (History)</div>
          <div class="custom-chart-wrapper" id="timelineChart">
            {timeline_svg}
          </div>
        </div>
      </section>

      <!-- SECTION 4: Hall of Fame & Big Numbers -->
      <section id="superlativesSection" class="dashboard-section">
        <div class="section-header">
          <div>
            <h2><span class="section-icon">🎖️</span> Hall of Fame & Superlatives (Big Numbers)</h2>
            <p class="section-desc">
              Classic IRC accolades, quirks, and achievements computed from chat patterns.
            </p>
          </div>
        </div>

        <div class="awards-grid" id="superlativesGrid">
          {superlatives_html}
        </div>
      </section>

      <!-- SECTION 5: Member Dossiers Archive (Zero-JS Accessible) -->
      <section id="dossiersSection" class="dashboard-section">
        <div class="section-header">
          <div>
            <h2><span class="section-icon">📁</span> Member Dossiers & Quotations Archive</h2>
            <p class="section-desc">
              Detailed participant profiles, top conversational partners, and memorable channel quotes. 
              Click any member to expand their dossier.
            </p>
          </div>
        </div>

        <div class="dossiers-container">
          {dossiers_html}
        </div>
      </section>

    </main>

    <!-- Footer -->
    <footer class="site-footer">
      <div class="footer-left">
        <span class="footer-brand">{data["channel"]} Stats</span> • Generated by IRC & Discord Statistics Engine (Pre-rendered Static HTML)
      </div>
      <div class="footer-right">
        Inspired by classic IRC stats: <em>pisg</em>, <em>mIRCStats</em> & <em>Denora</em>
      </div>
    </footer>

  </div>

  <!-- User Dossier Modal (Progressive Enhancement for JS-enabled browsers) -->
  <div class="modal-backdrop" id="userModal">
    <div class="modal-card">
      <button class="modal-close" id="modalCloseBtn">&times;</button>
      <div class="modal-header">
        <div class="user-avatar-badge" id="modalAvatar">#</div>
        <div>
          <h2 class="modal-username" id="modalName">Username</h2>
          <div class="modal-rank-badge" id="modalRank">Rank #1</div>
        </div>
      </div>

      <div class="modal-stats-grid">
        <div class="mstat-box">
          <div class="mstat-val" id="modalLines">0</div>
          <div class="mstat-lbl">Lines Spoken</div>
        </div>
        <div class="mstat-box">
          <div class="mstat-val" id="modalWords">0</div>
          <div class="mstat-lbl">Total Words</div>
        </div>
        <div class="mstat-box">
          <div class="mstat-val" id="modalWPL">0</div>
          <div class="mstat-lbl">Avg Words/Line</div>
        </div>
        <div class="mstat-box">
          <div class="mstat-val" id="modalPeakHour">—</div>
          <div class="mstat-lbl">Peak Hour</div>
        </div>
      </div>

      <div class="modal-section">
        <h3>💬 Top Conversation Partners (Connection Bonds)</h3>
        <div class="partners-list" id="modalPartners"></div>
      </div>

      <div class="modal-section">
        <h3>⏰ 24-Hour Activity Rhythm</h3>
        <div class="sparkline-wrapper" id="modalSparkline"></div>
      </div>

      <div class="modal-section">
        <h3>🗣️ Notable Quotes</h3>
        <div class="quotes-list" id="modalQuotes"></div>
      </div>
    </div>
  </div>

  <!-- Toast Notification -->
  <div class="toast" id="toast"></div>

  <!-- Progressive Enhancement Scripts (Optional: only enhances if JS is enabled) -->
  <script src="charts.js"></script>
  <script src="graph.js"></script>
  <script src="app.js"></script>
</body>
</html>
'''
    return html_content
