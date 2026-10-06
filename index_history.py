import json
import re
from pathlib import Path
import rag_store

BOT_DIR = Path(__file__).resolve().parent
DOCS_DIR = BOT_DIR / "docs"
MEMORY_FILE = BOT_DIR / "general_memory.json"
RAW_FILE = BOT_DIR / "current_chunk_raw.txt"

DOCS_DIR.mkdir(exist_ok=True)


def index_general_memory():
    if not MEMORY_FILE.exists():
        print(f"{MEMORY_FILE} not found.")
        return

    print(f"Indexing {MEMORY_FILE} into vector RAG database...")
    data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))

    count = 0
    channels = data.get("channels", {})
    for c_id, ch_data in channels.items():
        channel_name = ch_data.get("channel_name", c_id)
        chunks = ch_data.get("chunks", [])
        for idx, c in enumerate(chunks):
            summary = c.get("summary", "").strip()
            start = c.get("start", "")
            end = c.get("end", "")
            if summary:
                text = f"Channel #{channel_name} Long-Term Memory Summary ({start} to {end}):\n{summary}"
                emb = rag_store.sync_embed_text(text)
                if emb:
                    rag_store.add_chunk(text, emb, source=f"memory_summary:{channel_name}", channel_id=int(c_id) if c_id.isdigit() else None)
                    count += 1

    print(f"Indexed {count} memory summary chunks into RAG store.")


def index_raw_chat_history():
    if not RAW_FILE.exists():
        print(f"{RAW_FILE} not found.")
        return

    print(f"Indexing raw chat history ({RAW_FILE})...")
    raw_text = RAW_FILE.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    # Group into 10-line conversation blocks for embedding
    block_size = 10
    count = 0
    for i in range(0, len(lines), block_size):
        block = "\n".join(lines[i:i+block_size])
        if len(block) > 20:
            emb = rag_store.sync_embed_text(block)
            if emb:
                rag_store.add_chunk(block, emb, source="raw_discord_history")
                count += 1
                if count % 20 == 0:
                    print(f"Indexed {count} raw history blocks...")

    print(f"Finished indexing {count} raw history blocks.")


def index_docs_folder():
    print(f"Checking {DOCS_DIR} for custom files to index...")
    count = 0
    for file_path in DOCS_DIR.glob("**/*"):
        if file_path.is_file() and file_path.suffix in [".txt", ".md", ".json", ".csv"]:
            try:
                content = file_path.read_text(encoding="utf-8").strip()
                if not content:
                    continue
                # Split large documents into 500-character paragraphs
                paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]
                for idx, p in enumerate(paragraphs):
                    emb = rag_store.sync_embed_text(p)
                    if emb:
                        rag_store.add_chunk(p, emb, source=f"doc:{file_path.name}")
                        count += 1
            except Exception as e:
                print(f"Error indexing document {file_path.name}: {e}")

    print(f"Indexed {count} document chunks from docs/.")


if __name__ == "__main__":
    print("=== Starting RAG Vector Indexing ===")
    rag_store.init_rag_db()
    index_general_memory()
    index_raw_chat_history()
    index_docs_folder()
    print("=== RAG Vector Indexing Complete ===")
