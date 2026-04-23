"""Application entrypoint helpers."""

from .gui import WordPressUploaderApp


def launch_app() -> None:
    """Start the desktop application."""

    app = WordPressUploaderApp()
    app.run()