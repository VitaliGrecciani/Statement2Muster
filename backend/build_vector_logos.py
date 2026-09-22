import re
import os
import subprocess
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.svgPathPen import SVGPathPen

def round_path(d_str, decimals=2):
    # Round floating numbers in SVG path
    def repl(m):
        val = float(m.group(0))
        return f"{val:.{decimals}f}".rstrip('0').rstrip('.')
    return re.sub(r'[-+]?\d*\.\d+|\d+', repl, d_str)

def generate_svgs():
    font = TTFont('C:/Windows/Fonts/seguibl.ttf')
    glyph_set = font.getGlyphSet()

    # --- 1. Standard logo_s2m.svg (Full B2B version) ---
    # Width 372px, centered in 512x512
    scale = 372.0 / 4044.0
    dy = 320.0
    x_start = (512.0 - 372.0) / 2.0

    dx_S = x_start - 82.0 * scale
    dx_2 = x_start + (1055.0 + 120.0 - 90.0) * scale
    dx_M = x_start + (1055.0 + 120.0 + 1010.0 + 120.0 - 141.0) * scale

    pen_S = SVGPathPen(glyph_set)
    glyph_set['S'].draw(TransformPen(pen_S, (scale, 0, 0, -scale, dx_S, dy)))
    path_S = round_path(pen_S.getCommands())

    pen_2 = SVGPathPen(glyph_set)
    glyph_set['two'].draw(TransformPen(pen_2, (scale, 0, 0, -scale, dx_2, dy)))
    path_2 = round_path(pen_2.getCommands())

    pen_M = SVGPathPen(glyph_set)
    glyph_set['M'].draw(TransformPen(pen_M, (scale, 0, 0, -scale, dx_M, dy)))
    path_M = round_path(pen_M.getCommands())

    full_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <linearGradient id="tileGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e222b"/>
      <stop offset="100%" stop-color="#0c0e14"/>
    </linearGradient>

    <linearGradient id="numGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF7A1A"/>
      <stop offset="100%" stop-color="#E85D04"/>
    </linearGradient>

    <linearGradient id="letterGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="100%" stop-color="#E2E8F0"/>
    </linearGradient>

    <filter id="tileShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="16" stdDeviation="24" flood-color="#000000" flood-opacity="0.6"/>
    </filter>

    <filter id="glow2" x="-40%" y="-40%" width="180%" height="180%">
      <feDropShadow dx="0" dy="0" stdDeviation="12" flood-color="#FF7A1A" flood-opacity="0.35"/>
    </filter>
  </defs>

  <!-- Squircle Base Tile -->
  <rect x="24" y="24" width="464" height="464" rx="104" fill="url(#tileGrad)" stroke="#2d3340" stroke-width="3" filter="url(#tileShadow)"/>
  <rect x="26" y="26" width="460" height="460" rx="102" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1.5"/>

  <!-- Glyph S (Vector Path) -->
  <path d="{path_S}" fill="url(#letterGrad)"/>

  <!-- Glyph 2 (Vector Path with Glow) -->
  <g filter="url(#glow2)">
    <path d="{path_2}" fill="url(#numGrad)"/>
  </g>

  <!-- Glyph M (Vector Path) -->
  <path d="{path_M}" fill="url(#letterGrad)"/>

  <!-- Subtle Financial Underline Indicator: Base track across S2M, active orange bar matching digit 2 width -->
  <rect x="70" y="365" width="372" height="6" rx="3" fill="rgba(255,255,255,0.12)"/>
  <rect x="178" y="365" width="93" height="6" rx="3" fill="url(#numGrad)"/>
</svg>
"""

    # --- 2. Micro logo_s2m_micro.svg (Optimized for 16-32px) ---
    # Maximized glyph size (width 416px, larger scale), no outer shadow margin, no blur/glow, no underline
    m_scale = 416.0 / 4044.0
    m_dy = 328.0
    m_x_start = (512.0 - 416.0) / 2.0

    m_dx_S = m_x_start - 82.0 * m_scale
    m_dx_2 = m_x_start + (1055.0 + 120.0 - 90.0) * m_scale
    m_dx_M = m_x_start + (1055.0 + 120.0 + 1010.0 + 120.0 - 141.0) * m_scale

    pen_m_S = SVGPathPen(glyph_set)
    glyph_set['S'].draw(TransformPen(pen_m_S, (m_scale, 0, 0, -m_scale, m_dx_S, m_dy)))
    m_path_S = round_path(pen_m_S.getCommands())

    pen_m_2 = SVGPathPen(glyph_set)
    glyph_set['two'].draw(TransformPen(pen_m_2, (m_scale, 0, 0, -m_scale, m_dx_2, m_dy)))
    m_path_2 = round_path(pen_m_2.getCommands())

    pen_m_M = SVGPathPen(glyph_set)
    glyph_set['M'].draw(TransformPen(pen_m_M, (m_scale, 0, 0, -m_scale, m_dx_M, m_dy)))
    m_path_M = round_path(pen_m_M.getCommands())

    micro_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <!-- Full-bleed squircle tile for micro sizes (16-32px) -->
  <rect width="512" height="512" rx="112" fill="#12151C"/>
  <rect x="8" y="8" width="496" height="496" rx="104" fill="none" stroke="#2B3240" stroke-width="16"/>

  <!-- High-contrast Solid Pure Glyphs (No filters/shadows for crisp rendering) -->
  <path d="{m_path_S}" fill="#FFFFFF"/>
  <path d="{m_path_2}" fill="#FF7A1A"/>
  <path d="{m_path_M}" fill="#FFFFFF"/>
</svg>
"""

    out_s2m = Path(r"c:\Users\zorik\Documents\Obsidian Vault\10_Projects\Statement2Muster\landing\logo_s2m.svg")
    out_micro = Path(r"c:\Users\zorik\Documents\Obsidian Vault\10_Projects\Statement2Muster\landing\logo_s2m_micro.svg")

    out_s2m.write_text(full_svg, encoding="utf-8")
    out_micro.write_text(micro_svg, encoding="utf-8")

    print(f"Generated {out_s2m} ({len(full_svg)} bytes)")
    print(f"Generated {out_micro} ({len(micro_svg)} bytes)")

if __name__ == "__main__":
    generate_svgs()
