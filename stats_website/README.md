# 📊 IRC & Discord Channel Statistics Engine & Web Dashboard

Inspired by legendary IRC statistics generators (**mIRCStats**, **pisg**, and **Denora**), this application analyzes raw Discord chat history and RAG memory logs to generate a comprehensive, interactive statistics website.

It features an interactive **User Connections Network Graph** (mIRCStats Relation Map), **Most Active Participants Leaderboard & Charts**, **24-Hour & Day-of-Week Activity Trends**, **Hall of Fame Superlatives (Big Numbers)**, and **User Dossier Profiles**, with support for both **Modern Dark Theme** and **Classic 2000s Retro IRC Theme**.

---

## 🚀 Quick Start (Hosting Locally)

### 1. Start the Web Server
Launch the server in the background on port `8080`:
```bash
./stats_website/start_server.sh 8080
```
Open **[http://localhost:8080](http://localhost:8080)** in your browser!

### 2. Check Server Status
```bash
./stats_website/status.sh
```

### 3. Stop the Server
```bash
./stats_website/stop_server.sh
```

---

## 🌐 Features & IRC Stat Page Heritage

### 1. User Connections Network Graph (mIRCStats Relation Map)
- **Conversational Adjacency & Mentions**: Detects direct replies (within a 5-minute window) and inline mentions (`@username`, nicknames).
- **Interactive Force-Simulation**:
  - Node sizes scale with total messages sent.
  - Edge thickness and brightness scale with connection strength.
  - Hovering a member highlights their direct conversational network and dims unrelated nodes.
  - Clicking any node opens that member's detailed profile dossier.
  - Controls: Zoom in/out, pan, reset camera, min connection threshold filter, member search, and simulation pause/resume.

### 2. Most Active Participants (Top Talkers)
- **Interactive Bar Chart**: Visualizes the top 15 chatterboxes and their percentage of the conversation.
- **Classic Leaderboard Table**:
  - Rank (#1, #2, #3 badges)
  - Nickname (with intelligent alias normalization)
  - Total Lines Spoken
  - Percentage Share (with segmented progress bar)
  - Total Words & Average Words per Line
  - Peak Active Hour
  - Signature / Memorable Quote
  - Profile Dossier button

### 3. Hourly & Daily Activity Rhythm
- **24-Hour Distribution (00:00 - 23:00)**: Color-coded by time of day (Night, Morning, Afternoon, Evening) with server peak hour highlighted.
- **Day of Week Breakdown**: Monday through Sunday activity patterns.
- **Chronological Timeline**: 60-day volume trends across the server's history.

### 4. Hall of Fame & Superlatives (Big Numbers)
- 🗣️ **The Chatterbox**: Most total lines spoken.
- 📜 **The Novelist**: Highest average words per line.
- ⚡ **The Loudmouth**: Most all-caps messages.
- ❓ **The Inquisitive**: Most questions asked.
- 🦉 **The Night Owl**: Highest percentage of messages between midnight and 6 AM.
- 🌅 **The Early Bird**: Most active in the morning hours (6 AM - 12 PM).
- 🔗 **The Linkmaster**: Most URLs shared.
- ✨ **Emoji Connoisseur**: Most emotes used.
- 🤝 **Social Butterfly**: Connected to the most unique chatters.
- 💬 **Inseparable Duo**: Server pair with the strongest mutual conversational bond.

### 5. Dual Visual Themes
- **Modern Cyber Dark (Default)**: Deep obsidian cards, neon cyan/indigo accents, crisp typography.
- **Classic 2000s Retro IRC Theme**: Authentic vintage pisg/mIRCStats aesthetic with classic slate blue tables, monospace fonts, and blocky segmented progress bars.
- Switch between themes instantly using the **Tape / Sparkle** toggle button in the top right.

### 6. Live Re-Scanning
- Click the **🔄 Refresh Stats** button on the website to trigger an on-the-fly re-scan of logs without restarting the server.

---

## ☁️ Deploying to the Web (GitHub Pages, Netlify, Cloudflare Pages)

If you'd like to publish this page online for your Discord community:
1. Run the static exporter:
   ```bash
   python3 stats_website/export_static.py
   ```
2. The `stats_website/dist/` directory contains a 100% self-contained static website (`index.html`, `style.css`, `graph.js`, `charts.js`, `app.js`, and `data.json`).
3. Deploy `dist/` directly to GitHub Pages, Netlify, Cloudflare Pages, Vercel, or any Apache/Nginx web server. No Python backend required!
