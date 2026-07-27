import urllib.request
import ssl

urls = [
    "https://mydatalabs.in/",
    "https://mydatalabs.in/hormuz-index",
    "https://mydatalabs.in/app-static/css/style.css",
    "https://mydatalabs.in/app-static/js/theme.js",
    "https://mydatalabs.in/app-static/img/logo.png",
    "https://mydatalabs.in/app-static/img/favicon.png",
    "https://www.mydatalabs.in/"
]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

print("Testing Custom Live Domain (https://mydatalabs.in):")
for u in urls:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx) as res:
            data = res.read()
            print(f"  [{res.status} OK] ({len(data)} bytes) -> {u}")
    except Exception as e:
        print(f"  [FAILED {e}] -> {u}")
