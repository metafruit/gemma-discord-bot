# Gemma Discord Bot

An advanced, multimodal Discord bot powered by local LLMs via Ollama, featuring long-term conversational memory, RAG (Retrieval-Augmented Generation), grounded web search capabilities, and an integrated server stats dashboard.

---

## Features

- **Local LLM Inference**: Communicates directly with a local [Ollama](https://ollama.com/) instance (e.g., `gemma4:e2b`).
- **Multimodal Video & Picture Vision**: Analyzes both pictures and video clips (MP4, WebM, MOV) attached or linked in messages using an upstream multimodal parser (Gemini 3.8 Flash) with zero local VRAM overhead.
- **Hierarchical Memory Architecture**:
  - **Short-Term Context**: Captures recent channel conversations and rolling context windows.
  - **Long-Term Consolidated Memory**: Structured community lore, member profiles, and historical milestones.
  - **Memory Compression & Archival**: Automatic chunk compression preserving narrative history without overflowing model context windows (`memory_archive/`).
  - **RAG Retrieval**: SQLite-backed semantic vector retrieval (`rag_store.py`) supporting `EmbeddingGemma 2` with automatic fallback to `nomic-embed-text`.
- **Grounded Web Search**: Real-time factual search via Google AI Studio Gemini API with Google Search Grounding.
- **Discord Slash Commands & Interactions**:
  - Mention `@Gemma` in any channel to converse.
  - `/ask <prompt>`: Direct prompt queries.
  - `/clear`: Reset local channel turn history.
  - `/timeout [minutes]`: Put bot on temporary timeout.
  - `/untimeout`: Instantly restore bot activity.
- **Stats & Lore Dashboard**: Web application located in `stats_website/` with interactive charts and community activity metrics.

---

## Architecture & Project Structure

```
├── bot.py                  # Main Discord bot server and event loop
├── rag_store.py            # SQLite RAG vector storage and search engine
├── run_bot.sh              # Production startup script with PID locking & env loading
├── fetch_current_chunk.py  # Discord message fetcher for context building
├── index_history.py        # History indexing into vector RAG store
├── stats_website/          # Server statistics dashboard web app
├── requirements.txt        # Python package dependencies
└── .env.example            # Environment variables template
```

---

## Getting Started

### 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com/) running locally:
  ```bash
  ollama run gemma4:e2b
  ```

### 2. Installation

Clone this repository and install dependencies:

```bash
git clone https://github.com/<your-username>/gemma-discord-bot.git
cd gemma-discord-bot
pip install -r requirements.txt
```

### 3. Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Configure the variables inside `.env`:

```env
DISCORD_TOKEN="your_discord_bot_token"
GEMINI_API_KEY="your_optional_gemini_api_key"
OLLAMA_URL="http://localhost:11434"
OLLAMA_MODEL="gemma4:e2b"
NUM_CTX=24576
IMAGE_MEMORY_MAX_CHARS=55000
TEXT_MEMORY_MAX_CHARS=70000
```

### 4. Running the Bot

Run directly using Python:

```bash
python3 bot.py
```

Or using the production shell script:

```bash
chmod +x run_bot.sh
./run_bot.sh
```

---

## License

MIT
