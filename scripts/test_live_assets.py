import re
import urllib.request
from urllib.parse import urljoin

base_url = "https://mydatalabs-in.vercel.app/hormuz-index"
req = urllib.request.Request(base_url, headers={"User-Agent": "Mozilla/5.0"})

with urllib.request.urlopen(req) as response:
    html = response.read().decode("utf-8")

matches = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', html)

print("Checking assets on live Vercel page:")
for url in set(matches):
    if url.startswith("data:") or "fonts.googleapis" in url or "fonts.gstatic" in url:
        continue
    full_url = urljoin(base_url, url)
    try:
        a_req = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(a_req) as a_res:
            print(f"  [{a_res.status} OK]  -> {full_url}")
    except Exception as e:
        print(f"  [FAILED {e}] -> {full_url}")
