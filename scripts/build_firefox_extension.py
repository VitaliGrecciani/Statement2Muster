#!/usr/bin/env python3
"""
Deterministic build script for Firefox MV3 extension (`extension_firefox_build/`)
sourced directly from Chrome MV3 (`extension/`).

Guarantees that shared UI/parser/exporter files (`app.js`, `sidepanel.html`, styles,
assets, and `lib/*`) are 100% byte-for-byte identical between Chrome and Firefox.
Only `manifest.json` and `background.js` receive deterministic Firefox MV3 overrides.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CHROME_DIR = ROOT_DIR / "extension"
FIREFOX_DIR = ROOT_DIR / "extension_firefox_build"

FIREFOX_BACKGROUND_JS = """// Safe background script supporting both Firefox sidebarAction and Chrome sidePanel
if (typeof browser !== 'undefined' && browser.action && browser.sidebarAction) {
  browser.action.onClicked.addListener(() => {
    browser.sidebarAction.open().catch((err) => console.error("Error opening sidebar:", err));
  });
} else if (typeof chrome !== 'undefined' && chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.error("Error setting sidePanel behavior:", error));
}
"""


def transform_manifest(chrome_manifest: dict) -> dict:
    manifest = json.loads(json.dumps(chrome_manifest))
    manifest["name"] = "Statement2Muster DACH • DATEV & BMD"
    manifest["permissions"] = [p for p in manifest.get("permissions", []) if p != "sidePanel"]
    manifest.pop("side_panel", None)
    manifest["background"] = {"scripts": ["background.js"]}
    manifest["browser_specific_settings"] = {
        "gecko": {
            "id": "statement2master@banksync-dach.com",
            "strict_min_version": "109.0",
            "data_collection_permissions": {"required": ["none"]},
        }
    }
    manifest["sidebar_action"] = {
        "default_panel": "sidepanel.html",
        "default_icon": "icon_48.png",
        "default_title": "Statement2Muster DACH",
    }
    return manifest


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_firefox_extension(check_only: bool = False) -> dict:
    if not CHROME_DIR.is_dir():
        raise FileNotFoundError(f"Source directory not found: {CHROME_DIR}")

    chrome_manifest = json.loads((CHROME_DIR / "manifest.json").read_text(encoding="utf-8"))
    ff_manifest_bytes = (json.dumps(transform_manifest(chrome_manifest), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    ff_bg_bytes = FIREFOX_BACKGROUND_JS.encode("utf-8")

    if not check_only:
        if FIREFOX_DIR.exists():
            shutil.rmtree(FIREFOX_DIR)
        FIREFOX_DIR.mkdir(parents=True, exist_ok=True)
        for src in sorted(CHROME_DIR.rglob("*")):
            if src.is_dir():
                continue
            rel = src.relative_to(CHROME_DIR)
            if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                continue
            dst = FIREFOX_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if rel.as_posix() == "manifest.json":
                dst.write_bytes(ff_manifest_bytes)
            elif rel.as_posix() == "background.js":
                dst.write_bytes(ff_bg_bytes)
            else:
                shutil.copy2(src, dst)

    shared_hashes = {}
    platform_hashes = {}
    mismatches = []

    for src in sorted(CHROME_DIR.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(CHROME_DIR).as_posix()
        if any(part.startswith(".") or part == "__pycache__" for part in src.relative_to(CHROME_DIR).parts):
            continue
        dst = FIREFOX_DIR / rel
        if not dst.is_file():
            mismatches.append(f"Missing target file: {rel}")
            continue
        c_hash = sha256_file(src)
        f_hash = sha256_file(dst)
        if rel in ("manifest.json", "background.js"):
            expected_bytes = ff_manifest_bytes if rel == "manifest.json" else ff_bg_bytes
            actual_bytes = dst.read_bytes()
            matches_expected = (actual_bytes == expected_bytes)
            platform_hashes[rel] = {
                "chrome_sha256": c_hash,
                "firefox_sha256": f_hash,
                "matches_expected_transform": matches_expected,
            }
            if not matches_expected:
                mismatches.append(f"Firefox override mismatch on {rel}: target does not match transform output")
        else:
            shared_hashes[rel] = f_hash
            if c_hash != f_hash:
                mismatches.append(f"Hash mismatch on shared file {rel}: chrome={c_hash} firefox={f_hash}")

    if check_only and mismatches:
        raise RuntimeError("Firefox build parity check failed: " + "; ".join(mismatches))

    return {
        "chrome_dir": str(CHROME_DIR),
        "firefox_dir": str(FIREFOX_DIR),
        "shared_files": shared_hashes,
        "platform_overrides": platform_hashes,
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build & verify extension_firefox_build/ from extension/")
    parser.add_argument("--check", action="store_true", help="Verify parity without modifying files")
    args = parser.parse_args()
    summary = build_firefox_extension(check_only=args.check)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
