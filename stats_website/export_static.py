#!/usr/bin/env python3
"""
Static Website Export Script
Bundles the generated statistics and web assets into a standalone 'dist/' folder
that can be hosted on GitHub Pages, Netlify, Cloudflare Pages, Vercel, or Apache/Nginx.
"""

import shutil
from pathlib import Path
import stats_engine

STATS_DIR = Path(__file__).resolve().parent
WEB_DIR = STATS_DIR / "web"
DIST_DIR = STATS_DIR / "dist"

def export_static_site():
    print("Regenerating latest statistics data...")
    stats_engine.generate_and_save_data()

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    
    print(f"Exporting static website to {DIST_DIR}...")
    shutil.copytree(WEB_DIR, DIST_DIR)
    print("✅ Static export complete! The 'dist/' directory is ready to deploy to any web host.")

if __name__ == "__main__":
    export_static_site()
