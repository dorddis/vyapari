"""Download all catalogue car images from Wikimedia Commons.

Uses the Wikimedia API to resolve proper thumbnail URLs, with rate limiting.
"""
import json
import urllib.request
import urllib.parse
import os
import re
import ssl
import time

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
CATALOGUE = os.path.join(os.path.dirname(__file__), "catalogue.json")

HEADERS = {
    "User-Agent": "VyapariBot/1.0 (https://github.com/dorddis/vyapari; hackathon demo project) python-urllib"
}

ctx = ssl.create_default_context()

# Delay between requests (seconds) to avoid 429
DELAY = 1.5


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def get_extension(url):
    path = url.split("?")[0]
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
        return ext
    return ".jpg"


def extract_filename_from_url(url):
    """Extract the Wikimedia filename from a thumb URL.

    Example: .../thumb/5/5e/Maruti_Suzuki_Alto.jpg/800px-Maruti_Suzuki_Alto.jpg
    Returns: Maruti_Suzuki_Alto.jpg
    """
    # Try to get the filename from the path
    parts = url.split("/")
    # In thumb URLs, the actual filename is the second-to-last segment
    if "thumb" in parts:
        thumb_idx = parts.index("thumb")
        if len(parts) > thumb_idx + 3:
            return urllib.parse.unquote(parts[thumb_idx + 3])
    # Fallback: last segment before the size prefix
    last = parts[-1]
    if last.startswith(("800px-", "640px-", "1024px-", "400px-")):
        return urllib.parse.unquote(last.split("-", 1)[1])
    return urllib.parse.unquote(last)


def get_image_url_via_api(filename, width=800):
    """Use Wikimedia API to get proper image thumbnail URL."""
    api_url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": f"File:{filename}",
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": str(width),
        "format": "json",
    }
    query = urllib.parse.urlencode(params)
    full_url = f"{api_url}?{query}"

    req = urllib.request.Request(full_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for page_id, page in pages.items():
                if page_id == "-1":
                    return None  # File doesn't exist
                info = page.get("imageinfo", [{}])[0]
                # Prefer thumbnail URL at requested width
                thumb_url = info.get("thumburl")
                if thumb_url:
                    return thumb_url
                # Fallback to full URL
                return info.get("url")
    except Exception as e:
        print(f"    API error for {filename}: {e}")
        return None


def download_image(url, filepath):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = resp.read()
            with open(filepath, "wb") as f:
                f.write(data)
            size_kb = len(data) / 1024
            return True, f"{size_kb:.0f}KB"
    except Exception as e:
        return False, str(e)


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)

    with open(CATALOGUE, "r", encoding="utf-8") as f:
        catalogue = json.load(f)

    total = 0
    success = 0
    failed = []

    for car in catalogue["cars"]:
        car_id = car["id"]
        make = slugify(car["make"])
        model = slugify(car["model"])
        prefix = f"{car_id:02d}_{make}_{model}"

        for idx, url in enumerate(car["images"]):
            ext = get_extension(url)
            if len(car["images"]) == 1:
                filename = f"{prefix}{ext}"
            else:
                filename = f"{prefix}_{idx + 1}{ext}"

            filepath = os.path.join(IMAGES_DIR, filename)
            total += 1

            if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
                size_kb = os.path.getsize(filepath) / 1024
                print(f"  SKIP {filename} (already exists, {size_kb:.0f}KB)")
                success += 1
                continue

            # Extract wiki filename and use API to get proper URL
            wiki_filename = extract_filename_from_url(url)
            print(f"  [{total:02d}] Resolving {wiki_filename}...", end=" ", flush=True)

            time.sleep(DELAY)
            resolved_url = get_image_url_via_api(wiki_filename)

            if not resolved_url:
                print(f"NOT FOUND on Commons")
                failed.append((filename, url, "File not found on Wikimedia Commons"))
                continue

            time.sleep(DELAY)
            ok, info = download_image(resolved_url, filepath)
            if ok:
                print(f"OK ({info})")
                success += 1
            else:
                print(f"FAIL: {info}")
                failed.append((filename, url, info))

    print(f"\nDone: {success}/{total} downloaded")
    if failed:
        print(f"\nFailed ({len(failed)}):")
        for name, url, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
