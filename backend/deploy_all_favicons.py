import os
import subprocess
from pathlib import Path
from PIL import Image

def render_svg_to_png(svg_path: Path, out_png: Path, size: int):
    """
    Renders an SVG file to a PNG of exactly size x size using Headless Edge.
    """
    temp_html = svg_path.parent / f"_temp_render_{size}.html"
    temp_html.write_text(f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {size}px; height: {size}px; background: transparent; overflow: hidden; }}
  img {{ width: {size}px; height: {size}px; display: block; }}
</style>
</head>
<body>
<img src="{svg_path.name}">
</body>
</html>
""", encoding="utf-8")

    edge_bin = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    cmd = [
        edge_bin,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={size},{size}",
        f"--screenshot={str(out_png.resolve())}",
        temp_html.resolve().as_uri()
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if temp_html.exists():
        temp_html.unlink()
    
    if out_png.exists():
        # Ensure exact dimensions with PIL in case of viewport borders
        with Image.open(out_png) as im:
            if im.size != (size, size):
                resized = im.resize((size, size), Image.Resampling.LANCZOS)
                resized.save(out_png, format="PNG")
        print(f"[OK] Rendered {out_png.name} ({size}x{size})")
    else:
        print(f"[ERROR] Failed rendering {out_png.name}: {res.stderr}")

def main():
    root = Path(r"c:\Users\zorik\Documents\Obsidian Vault\10_Projects\Statement2Muster")
    landing = root / "landing"
    extension = root / "extension"
    firefox_ext = root / "extension_firefox_build"

    svg_micro = landing / "logo_s2m_micro.svg"
    svg_full = landing / "logo_s2m.svg"

    # Temporary staging directory for clean masters
    staging = landing / "renders" / "staging"
    staging.mkdir(parents=True, exist_ok=True)

    master_16 = staging / "icon_16.png"
    master_32 = staging / "icon_32.png"
    master_48 = staging / "icon_48.png"
    master_128 = staging / "icon_128.png"
    master_180 = staging / "icon_180.png"
    master_512 = staging / "icon_512.png"

    # 16 & 32 use micro SVG (optimized, full bleed, no glow/shadow blur)
    render_svg_to_png(svg_micro, master_16, 16)
    render_svg_to_png(svg_micro, master_32, 32)

    # 48, 128, 180, 512 use full SVG (depth, subtle borders, glow, underline)
    render_svg_to_png(svg_full, master_48, 48)
    render_svg_to_png(svg_full, master_128, 128)
    render_svg_to_png(svg_full, master_180, 180)
    render_svg_to_png(svg_full, master_512, 512)

    # Deploy to landing/
    img_16 = Image.open(master_16)
    img_32 = Image.open(master_32)
    img_48 = Image.open(master_48)
    img_180 = Image.open(master_180)
    img_512 = Image.open(master_512)

    img_16.save(landing / "favicon-16x16.png", format="PNG")
    img_32.save(landing / "favicon-32x32.png", format="PNG")
    img_180.save(landing / "apple-touch-icon.png", format="PNG")
    img_512.save(landing / "logo.png", format="PNG")

    # Generate multi-resolution favicon.ico containing 16x16, 32x32, 48x48
    ico_path = landing / "favicon.ico"
    img_16_rgba = img_16.convert("RGBA")
    img_32_rgba = img_32.convert("RGBA")
    img_48_rgba = img_48.convert("RGBA")
    img_16_rgba.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[img_32_rgba, img_48_rgba]
    )
    print(f"[OK] Generated multi-size favicon.ico ({ico_path.stat().st_size} bytes)")

    # Deploy to extension/
    img_16.save(extension / "icon_16.png", format="PNG")
    img_48.save(extension / "icon_48.png", format="PNG")
    img_128 = Image.open(master_128)
    img_128.save(extension / "icon_128.png", format="PNG")
    img_512.save(extension / "icon.png", format="PNG")
    store_assets = extension / "store_assets"
    if store_assets.exists():
        img_300 = img_512.resize((300, 300), Image.Resampling.LANCZOS)
        img_300.save(store_assets / "logo_300x300.png", format="PNG")
    print(f"[OK] Deployed icons to Chrome extension directory ({extension})")

    # Deploy to extension_firefox_build/ if it exists
    if firefox_ext.exists():
        img_16.save(firefox_ext / "icon_16.png", format="PNG")
        img_48.save(firefox_ext / "icon_48.png", format="PNG")
        img_128.save(firefox_ext / "icon_128.png", format="PNG")
        img_512.save(firefox_ext / "icon.png", format="PNG")
        print(f"[OK] Deployed icons to Firefox extension directory ({firefox_ext})")

if __name__ == "__main__":
    main()
