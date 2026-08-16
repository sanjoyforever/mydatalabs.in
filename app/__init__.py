import os
from datetime import date

from flask import Flask, render_template, request

# Static assets are versioned by the ?v= query string emitted in base.html, so
# they can be cached hard. Without this Flask serves them with `no-cache` and
# every navigation re-downloads the CSS, JS and images.
STATIC_MAX_AGE = int(os.environ.get("STATIC_MAX_AGE", 60 * 60 * 24 * 365))

# GA4 property tagged sitewide. base.html loads gtag.js on every page (a
# page_view fires automatically on each server-rendered load), and theme.js
# sends custom events for copy actions, the theme toggle, and outbound clicks.
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "G-3376VRHZW8")

# Microsoft Clarity session recording and heatmaps, loaded sitewide from
# base.html alongside GA4. Clarity is behaviour-only (no pageview metrics), so
# it complements rather than replaces the GA4 tag.
CLARITY_PROJECT_ID = os.environ.get("CLARITY_PROJECT_ID", "y3gm1j4qyn")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "X-Frame-Options": "SAMEORIGIN",
}

# ECharts is loaded from jsDelivr, fonts from Google Fonts, GA4 from
# googletagmanager.com/google-analytics.com, Clarity from *.clarity.ms (the
# bootstrap tag injects a second script from a region-specific subdomain, and
# the recorder ships payloads to *.clarity.ms and c.bing.com). Inline styles
# remain in the templates, so style-src still needs 'unsafe-inline' until those
# are fully migrated to classes; the gtag and Clarity inline bootstrap snippets
# need the same for script-src.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
    " https://www.googletagmanager.com https://*.google-analytics.com"
    " https://*.clarity.ms",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https://*.google-analytics.com https://*.googletagmanager.com"
    " https://*.clarity.ms",
    "connect-src 'self' https://*.google-analytics.com https://*.analytics.google.com"
    " https://www.googletagmanager.com https://*.clarity.ms https://c.bing.com",
    "frame-ancestors 'self'",
    "base-uri 'self'",
    "form-action 'self'",
])


def _static_version(static_folder: str | None) -> str:
    """Cache-busting token for /static, changed by every deploy.

    Prefers the deployed commit SHA. The mtime fallback below is correct on a
    normal filesystem but useless on Vercel, which normalises every checked-out
    file to one fixed timestamp for reproducible builds: every deploy then
    emits the same token, and since vercel.json marks /static immutable for a
    year, returning visitors keep running last year's JS against this year's
    HTML. That combination is silent — the stale script simply fails to find
    the elements it wants — so it has to be prevented rather than noticed.
    """
    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA")
    if sha:
        return sha[:12]

    newest = 0.0
    if static_folder and os.path.isdir(static_folder):
        for root, _dirs, files in os.walk(static_folder):
            for name in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    continue
    return str(int(newest))


def create_app() -> Flask:
    app_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        static_folder=os.path.join(app_dir, "static"),
        static_url_path="/static",
        template_folder=os.path.join(app_dir, "templates"),
    )
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = STATIC_MAX_AGE

    from app.elections.routes import bp as elections_bp
    from app.routes import bp

    app.register_blueprint(bp)
    app.register_blueprint(elections_bp)

    # Cache-busting token for /static assets. Derived from the newest mtime in
    # the static tree so a deploy invalidates the year-long cache above.
    asset_version = _static_version(app.static_folder)

    @app.context_processor
    def inject_defaults():
        # Error templates extend base.html, so these have to be available
        # outside the normal route context too.
        return {
            "asset_v": asset_version,
            "current_year": date.today().year,
            "ga_measurement_id": GA_MEASUREMENT_ID,
            "clarity_project_id": CLARITY_PROJECT_ID,
        }

    @app.after_request
    def set_headers(resp):
        for header, value in SECURITY_HEADERS.items():
            resp.headers.setdefault(header, value)
        resp.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = f"public, max-age={STATIC_MAX_AGE}, immutable"
        return resp

    @app.errorhandler(404)
    def not_found_error(e):
        # A missing page is not a server failure. Rendering the 500 template
        # here told every visitor with a typo'd URL that the site was broken.
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("500.html"), 500

    return app
