import os
from flask import Flask


def create_app() -> Flask:
    app_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        static_folder=os.path.join(app_dir, "static"),
        static_url_path="/static",
        template_folder=os.path.join(app_dir, "templates"),
    )

    from app.routes import bp

    app.register_blueprint(bp)
    return app
