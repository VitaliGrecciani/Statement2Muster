import re
from pathlib import Path

def update_html_files():
    landing = Path(r"c:\Users\zorik\Documents\Obsidian Vault\10_Projects\Statement2Muster\landing")
    html_files = list(landing.glob("*.html"))
    print(f"Found {len(html_files)} HTML files in {landing}")

    old_favicon_pattern = re.compile(
        r'<!-- Favicons -->.*?(?=<link rel="stylesheet"|<link rel="canonical"|</head>)',
        re.DOTALL
    )

    new_favicons = """<!-- Favicons -->
  <link rel="icon" type="image/svg+xml" href="logo_s2m_micro.svg?v=2">
  <link rel="icon" type="image/png" sizes="32x32" href="favicon-32x32.png?v=2">
  <link rel="icon" type="image/png" sizes="16x16" href="favicon-16x16.png?v=2">
  <link rel="shortcut icon" href="favicon.ico?v=2">
  <link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png?v=2">
  """

    brand_logo_markup = """<div class="brand-logo">
          <img src="logo_s2m.svg" alt="S2M Logo" class="brand-logo-img">
        </div>
        <div class="brand-text">"""

    for f in html_files:
        content = f.read_text(encoding="utf-8")
        orig = content

        # 1. Update favicons
        if "<!-- Favicons -->" in content:
            content = old_favicon_pattern.sub(new_favicons, content)
        else:
            # If no comment, look for existing favicon tags and replace
            content = re.sub(
                r'(<link rel="(?:icon|shortcut icon|apple-touch-icon)"[^>]+>\s*)+',
                new_favicons,
                content
            )

        # 2. Add brand-logo to nav-brand if missing
        if '<div class="nav-brand">' in content and '<div class="brand-logo">' not in content:
            content = content.replace(
                '<div class="nav-brand">\n        <div class="brand-text">',
                f'<div class="nav-brand">\n        {brand_logo_markup}'
            ).replace(
                '<div class="nav-brand">\r\n        <div class="brand-text">',
                f'<div class="nav-brand">\r\n        {brand_logo_markup}'
            )

        if content != orig:
            f.write_text(content, encoding="utf-8")
            print(f"[UPDATED] {f.name}")
        else:
            print(f"[UNCHANGED] {f.name}")

if __name__ == "__main__":
    update_html_files()
