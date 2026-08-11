# Copyright 2026 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
"""Access to the mender-server compose files shipped as package data.

importlib.resources exposes package data as a Traversable, not a filesystem
path -- in a zipped install there is no path at all. Docker compose needs real
files, and it needs them as a *tree*: docker-compose.yml binds ./compose/certs,
./compose/config/traefik and ./compose/config/mender.pem relative to the project
directory, and it `include:`s compose/docker-compose.seaweedfs.yml. So the whole
directory is materialised together rather than a file at a time.

importlib.resources.as_file() is the usual answer for a single resource, but its
temporary copy is removed when the context manager exits, which is no good for
paths that have to outlive a `compose up` ... `compose down` cycle.
"""

import atexit
import logging
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_ROOT = ("data", "mender_server")
# Overrides written by this package rather than vendored from mender-server, so
# they live outside the tree scripts/vendor.py regenerates.
_OVERLAY_ROOT = ("data", "overlays")

# Materialised at most once per process, so `up` and `down` are handed identical
# paths. Under xdist each worker gets its own copy, which costs 31 KB.
_materialised = None


def _copy_tree(src, dest: Path) -> None:
    """Recursively copy a Traversable into a real directory.

    Written against the Traversable API rather than shutil.copytree so that it
    works whether the package is installed as a directory or inside a zip.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            _copy_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


def compose_dir(dest=None) -> Path:
    """Real on-disk directory holding mender-server's compose tree.

    Pass this as compose's --project-directory so the relative bind mounts in
    docker-compose.yml resolve. This package's own overrides are materialised
    alongside, under overlays/.

    With no `dest` the tree goes to a temporary directory removed at process
    exit, which suits a pytest session. Pass `dest` to materialise somewhere
    that outlives this process -- handing the path to a shell script, say.
    """
    global _materialised

    def _build(target: Path) -> None:
        _copy_tree(_resource(_DATA_ROOT), target)
        _copy_tree(_resource(_OVERLAY_ROOT), target / "overlays")

    if dest is not None:
        dest = Path(dest)
        _build(dest)
        return dest
    if _materialised is None:
        tmp = Path(tempfile.mkdtemp(prefix="mender-compose-"))
        _build(tmp)
        atexit.register(shutil.rmtree, tmp, ignore_errors=True)
        logger.debug("materialised mender-server compose files to %s", tmp)
        _materialised = tmp
    return _materialised


def _resource(parts):
    root = files(__package__)
    for part in parts:
        root = root / part
    return root


def compose_files(plan: str = "os", publish_ports: bool = False, dest=None) -> list:
    """Compose files for `plan`, in the order they must be passed to -f.

    By default the backend publishes no host ports: the tests reach Traefik by
    container IP, and not publishing lets several backends coexist. Pass
    publish_ports=True to reach the stack from the host, which only works for one
    backend at a time.
    """
    d = compose_dir(dest)
    paths = [d / "docker-compose.yml"]
    if plan == "enterprise":
        paths.append(d / "compose" / "docker-compose.enterprise.yml")
    if not publish_ports:
        # Last, so it overrides whatever the files above declared.
        paths.append(d / "overlays" / "no-ports.yml")
    return paths
