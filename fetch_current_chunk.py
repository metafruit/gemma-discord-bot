import os
import re
import json
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import discord

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE_PATH = Path(os.environ.get("MEMORY_FILE", BASE_DIR / "general_memory.json"))
META_FILE_PATH = Path(os.environ.get("META_FILE", BASE_DIR / "current_chunk_meta.json"))
RAW_LOG_PATH = Path(os.environ.get("RAW_LOG_PATH", BASE_DIR / "current_chunk_raw.txt"))
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "497252525569736706"))

# Extract token
def get_token():
    token = os.environ.get("DISCORD_TOKEN")
    if token:
        return token
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DISCORD_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("No DISCORD_TOKEN found in environment or .env")

class DailyFetcher(discord.Client):
    async def on_ready(self):
        print(f"Logged in as {self.user}")
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            try:
                channel = await self.fetch_channel(CHANNEL_ID)
            except Exception as e:
                print(f"Error fetching channel: {e}")
                await self.close()
                return

        # Load existing memory to find current chunk dates
        with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
            memory = json.load(f)

        channel_data = memory.get("channels", {}).get(str(CHANNEL_ID))
        if not channel_data:
            print("Error: Channel data not found in memory file.")
            await self.close()
            return

        chunks = channel_data.get("chunks", [])
        if not chunks:
            print("Error: No chunks found in memory file to refresh.")
            await self.close()
            return

        last_chunk = chunks[-1]
        start_dt = datetime.fromisoformat(last_chunk["start"])
        now = datetime.now(timezone.utc)

        # If last chunk has been active for >= 30 days, we roll over to a new chunk
        if now - start_dt >= timedelta(days=30):
            print("Active chunk is older than 30 days. Creating a new chunk slot.")
            fetch_start = datetime.fromisoformat(last_chunk["end"])
            is_new_chunk = True
            chunk_index = len(chunks)
        else:
            print("Active chunk is less than 30 days old. Updating existing chunk.")
            fetch_start = start_dt
            is_new_chunk = False
            chunk_index = len(chunks) - 1

        print(f"Fetching messages from {fetch_start.date()} to {now.date()}...")

        lines = []
        count = 0
        async for msg in channel.history(after=fetch_start, before=now, oldest_first=True, limit=None):
            count += 1
            if count % 500 == 0:
                print(f"Processed {count} messages from Discord API...", flush=True)
            if msg.author == self.user:
                continue
            
            timestamp = msg.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
            content = msg.content.strip()
            if content:
                lines.append(f"[{timestamp}] {msg.author.display_name}: {content}")

        # Save metadata
        meta = {
            "chunk_index": chunk_index,
            "is_new_chunk": is_new_chunk,
            "start": fetch_start.isoformat(),
            "end": now.isoformat(),
            "message_count": len(lines)
        }
        with open(META_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # Save raw log lines
        with open(RAW_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"Fetched {len(lines)} messages. Saved raw logs to {RAW_LOG_PATH} and metadata to {META_FILE_PATH}", flush=True)
        await self.close()

async def main():
    token = get_token()
    intents = discord.Intents.default()
    intents.message_content = True
    client = DailyFetcher(intents=intents)
    await client.start(token)

if __name__ == "__main__":
    asyncio.run(main())
