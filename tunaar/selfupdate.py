"""One-click self-update for the admin console.

``check()`` compares the running image against the registry. ``apply()`` pulls
the newer image and launches a short-lived **helper** container (from the new
image, with the Docker socket mounted) that recreates the Tunaar container —
because a container can't cleanly replace itself while it's running. The helper
rolls back to the old container if anything goes wrong, so a failed update
shouldn't leave you with no Tunaar.

Requires the Docker socket mounted into the container:
``-v /var/run/docker.sock:/var/run/docker.sock`` and a public image.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.request

from .dockerapi import DockerClient, DockerError

log = logging.getLogger("tunaar")

DEFAULT_IMAGE = "ghcr.io/mchammer65/plexiptv:latest"
HELPER_NAME = "tunaar-updater"


def _split_ref(ref: str) -> tuple[str, str]:
    """Split ``repo[:tag]`` into ``(repo, tag)``; ignores digest refs."""
    if "@" in ref or not ref:
        return DEFAULT_IMAGE.rsplit(":", 1)[0], "latest"
    if ":" in ref.rsplit("/", 1)[-1]:
        repo, tag = ref.rsplit(":", 1)
        return repo, tag
    return ref, "latest"


def _image_ref(me: dict) -> str:
    override = os.environ.get("TUNAAR_UPDATE_IMAGE")
    if override:
        return override
    cfg_image = (me.get("Config") or {}).get("Image") or ""
    if cfg_image and "@" not in cfg_image:
        return cfg_image
    return DEFAULT_IMAGE


def _registry_digest(repo: str, tag: str) -> str | None:
    """Best-effort current digest for ``repo:tag`` from a v2 registry (GHCR)."""
    try:
        host, name = repo.split("/", 1)
        token_url = (
            f"https://{host}/token?scope=repository:{name}:pull&service={host}"
        )
        with urllib.request.urlopen(token_url, timeout=15) as r:
            token = json.loads(r.read()).get("token", "")
        req = urllib.request.Request(
            f"https://{host}/v2/{name}/manifests/{tag}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.oci.image.index.v1+json,"
                "application/vnd.docker.distribution.manifest.list.v2+json,"
                "application/vnd.docker.distribution.manifest.v2+json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.headers.get("Docker-Content-Digest")
    except Exception:  # noqa: BLE001 - check is best-effort
        return None


def check(client: DockerClient | None = None) -> dict:
    if not DockerClient.available():
        return {"socket": False, "message": "Docker socket not mounted"}
    client = client or DockerClient()
    try:
        me = client.inspect_container(client.self_id())
        ref = _image_ref(me)
        repo, tag = _split_ref(ref)
        local = client.inspect_image(me["Image"]).get("RepoDigests", []) or []
        remote = _registry_digest(repo, tag)
        if not remote:
            return {"socket": True, "image": ref, "update_available": None,
                    "message": "could not reach registry"}
        up_to_date = any(remote in d for d in local)
        return {
            "socket": True,
            "image": ref,
            "current": me["Image"][:19],
            "remote_digest": remote,
            "update_available": not up_to_date,
        }
    except DockerError as exc:
        return {"socket": True, "error": str(exc)}


def _build_spec(me: dict, ref: str) -> dict:
    cfg = me.get("Config") or {}
    host = me.get("HostConfig") or {}
    return {
        "Image": ref,
        "Env": cfg.get("Env"),
        "Labels": cfg.get("Labels"),
        "ExposedPorts": cfg.get("ExposedPorts"),
        "HostConfig": {
            "Binds": host.get("Binds"),
            "Mounts": host.get("Mounts"),
            "NetworkMode": host.get("NetworkMode"),
            "RestartPolicy": host.get("RestartPolicy"),
            "PortBindings": host.get("PortBindings"),
        },
    }


def apply(client: DockerClient | None = None) -> dict:
    if not DockerClient.available():
        return {"ok": False, "message": "Docker socket not mounted; update via SSH"}
    client = client or DockerClient()
    me = client.inspect_container(client.self_id())
    name = (me.get("Name") or "/tunaar").lstrip("/")
    ref = _image_ref(me)
    repo, tag = _split_ref(ref)

    log.warning("Self-update: pulling %s", ref)
    client.pull(repo, tag)
    new_id = client.inspect_image(ref).get("Id")
    if new_id == me.get("Image"):
        log.info("Self-update: already running the latest image")
        return {"ok": True, "updated": False, "message": "Already up to date"}

    spec = _build_spec(me, ref)
    helper_spec = {
        "Image": ref,
        "Entrypoint": ["python", "-m", "tunaar.selfupdate"],
        "Env": [
            "TUNAAR_SELFUPDATE_HELPER=1",
            f"TUNAAR_TARGET_NAME={name}",
            f"TUNAAR_OLD_ID={me['Id']}",
            f"TUNAAR_SPEC={json.dumps(spec)}",
        ],
        "HostConfig": {
            "Binds": ["/var/run/docker.sock:/var/run/docker.sock"],
            "NetworkMode": "bridge",
            "AutoRemove": True,
        },
    }
    try:
        client.remove(HELPER_NAME)  # clear a stale helper if present
    except DockerError:
        pass
    hid = client.create_container(HELPER_NAME, helper_spec)
    client.start(hid)
    log.warning("Self-update: helper launched, recreating container shortly")
    return {"ok": True, "updated": True, "message": "Updating — reconnect in a moment"}


def _run_helper() -> int:
    """Entrypoint inside the helper container: recreate Tunaar, with rollback."""
    client = DockerClient()
    old = os.environ["TUNAAR_OLD_ID"]
    name = os.environ["TUNAAR_TARGET_NAME"]
    spec = json.loads(os.environ["TUNAAR_SPEC"])
    time.sleep(3)  # let the old container flush its HTTP response

    try:
        client.stop(old)
        client.rename(old, f"{name}-old")
        new_id = client.create_container(name, spec)
        client.start(new_id)
        client.remove(old)  # success: drop the old container
        print("self-update: recreated", name)
        return 0
    except Exception as exc:  # noqa: BLE001 - rollback on any failure
        print("self-update failed, rolling back:", exc)
        try:
            client.remove(name)
        except Exception:
            pass
        try:
            client.rename(old, name)
            client.start(old)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    if os.environ.get("TUNAAR_SELFUPDATE_HELPER") == "1":
        sys.exit(_run_helper())
    print(json.dumps(check(), indent=2))
