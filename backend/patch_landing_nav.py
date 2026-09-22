import re
from pathlib import Path

def patch_landing_nav():
    landing = Path(r"c:\Users\zorik\Documents\Obsidian Vault\10_Projects\Statement2Muster\landing")
    html_files = list(landing.glob("*.html"))

    for h in html_files:
        if not h.name.endswith(".html"):
            continue
        text = h.read_text(encoding="utf-8")
        orig = text

        # Remove redundant Live-Demo link from nav-links
        text = re.sub(r'\s*<a href="[^"]*#demo"[^>]*>Live-Demo</a>', '', text)

        # Make sure stylesheet has cache-busting v=2.3
        text = re.sub(r'href="styles\.css(\?v=[^"]*)?"', 'href="styles.css?v=2.3"', text)

        if text != orig:
            h.write_text(text, encoding="utf-8")
            print(f"Patched HTML: {h.name}")

if __name__ == "__main__":
    patch_landing_nav()
