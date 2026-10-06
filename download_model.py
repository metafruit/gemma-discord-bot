import asyncio
import httpx
import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
URL = "https://huggingface.co/unsloth/embeddinggemma-2-GGUF/resolve/main/embeddinggemma-2-UD-Q4_K_XL.gguf"
OUTPUT = str(BASE_DIR / "models" / "embeddinggemma-2-UD-Q4_K_XL.gguf")
NUM_CHUNKS = 8

async def download_chunk(client, url, start, end, chunk_idx, temp_path):
    expected_len = end - start + 1
    # Check if already downloaded
    if os.path.exists(temp_path):
        current_len = os.path.getsize(temp_path)
        if current_len == expected_len:
            print(f"Chunk {chunk_idx+1}/{NUM_CHUNKS} already fully downloaded ({expected_len} bytes)")
            return
        elif current_len < expected_len:
            print(f"Chunk {chunk_idx+1}/{NUM_CHUNKS} resuming from byte {current_len}/{expected_len}...")
            start = start + current_len
            mode = "ab"
        else:
            mode = "wb"
    else:
        mode = "wb"

    retries = 5
    for attempt in range(retries):
        try:
            headers = {"Range": f"bytes={start}-{end}"}
            async with client.stream("GET", url, headers=headers, follow_redirects=True, timeout=120.0) as resp:
                if resp.status_code not in (200, 206):
                    raise RuntimeError(f"Chunk {chunk_idx} failed with status {resp.status_code}")
                with open(temp_path, mode) as f:
                    async for data in resp.aiter_bytes(chunk_size=65536):
                        f.write(data)
            print(f"Chunk {chunk_idx+1}/{NUM_CHUNKS} finished!")
            return
        except Exception as e:
            print(f"Chunk {chunk_idx+1} error on attempt {attempt+1}: {e}")
            if os.path.exists(temp_path):
                current_len = os.path.getsize(temp_path)
                start = (end - expected_len + 1) + current_len
                mode = "ab"
            await asyncio.sleep(2)
    raise RuntimeError(f"Chunk {chunk_idx+1} failed after {retries} attempts")

async def main():
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        head_resp = await client.head(URL)
        total_size = int(head_resp.headers.get("content-length", 0))
        if total_size == 0:
            get_resp = await client.get(URL, headers={"Range": "bytes=0-1"})
            cr = get_resp.headers.get("content-range", "")
            if "/" in cr:
                total_size = int(cr.split("/")[-1])
        
        chunk_size = total_size // NUM_CHUNKS
        tasks = []
        temp_files = []
        
        for i in range(NUM_CHUNKS):
            start = i * chunk_size
            end = (start + chunk_size - 1) if i < NUM_CHUNKS - 1 else total_size - 1
            temp_path = f"{OUTPUT}.part{i}"
            temp_files.append(temp_path)
            tasks.append(download_chunk(client, URL, start, end, i, temp_path))
        
        await asyncio.gather(*tasks)
        
        print("Assembling parts into final GGUF...")
        with open(OUTPUT, "wb") as outfile:
            for temp_path in temp_files:
                with open(temp_path, "rb") as infile:
                    while True:
                        block = infile.read(1048576)
                        if not block:
                            break
                        outfile.write(block)
                os.remove(temp_path)
                
        final_size = os.path.getsize(OUTPUT)
        print(f"SUCCESS! Assembled {OUTPUT} ({final_size / (1024*1024):.2f} MB)")

if __name__ == "__main__":
    asyncio.run(main())
