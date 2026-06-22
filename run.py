#!/usr/bin/env python3
"""Entry point for running the Tunaar server."""

from tunaar import APP_NAME, __version__, discovery
from tunaar.app import create_app
from tunaar.config import Config


def main() -> None:
    config = Config.load()
    app = create_app(config)

    print(
        f"{APP_NAME} v{__version__} — device {config.device_id} — "
        f"{config.tuner_count} tuner(s), mode={config.stream_mode} — "
        f"listening on {config.host}:{config.port}"
    )

    if config.discovery:
        try:
            discovery.start(config, port=config.discovery_port)
            print(f"HDHomeRun discovery responding on UDP {config.discovery_port}")
        except OSError as exc:
            print(f"discovery disabled (couldn't bind UDP {config.discovery_port}): {exc}")

    # waitress is a production-grade WSGI server that handles streaming
    # responses well; fall back to Flask's dev server if it's unavailable.
    try:
        from waitress import serve

        # Enough threads for every tuner plus dashboard/API traffic.
        serve(
            app,
            host=config.host,
            port=config.port,
            threads=config.tuner_count + 8,
            channel_timeout=300,
        )
    except ImportError:
        app.run(host=config.host, port=config.port, threaded=True)


if __name__ == "__main__":
    main()
