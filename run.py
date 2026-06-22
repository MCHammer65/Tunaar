#!/usr/bin/env python3
"""Entry point for running the PlexIPTV HDHomeRun emulator."""

from plexiptv.app import create_app
from plexiptv.config import Config


def main() -> None:
    config = Config.load()
    app = create_app(config)
    print(
        f"PlexIPTV '{config.friendly_name}' serving "
        f"{config.tuner_count} tuner(s) on {config.host}:{config.port}"
    )
    app.run(host=config.host, port=config.port, threaded=True)


if __name__ == "__main__":
    main()
