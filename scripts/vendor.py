#!/usr/bin/env python3
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
"""Refresh the vendored mender-server trees to MENDER_SERVER_REF.

    scripts/vendor.py [--check]

Copies, from the pinned commit:

  * backend/tests/testutils/  -> src/mender_testkit/testutils/ (imports namespaced)
  * the compose surface       -> src/mender_testkit/data/mender_server/

--check exits non-zero if either tree differs from the pin, so CI can catch a
hand-edit or a Renovate bump whose files were never regenerated.

The compose file list is derived, not hardcoded: COMPOSE_ROOTS plus every
`include:` target they name plus every relative bind source. Deriving it is the
point -- compose/docker-compose.seaweedfs.yml is reachable only through an
`include:` in docker-compose.yml and is easy to miss by inspection.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = "https://github.com/mendersoftware/mender-server.git"

TESTUTILS_SRC = "backend/tests/testutils"
TESTUTILS_DEST = REPO / "src" / "mender_testkit" / "testutils"
COMPOSE_DEST = REPO / "src" / "mender_testkit" / "data" / "mender_server"

# Entry points; everything else is discovered from these.
COMPOSE_ROOTS = ["docker-compose.yml", "compose/docker-compose.enterprise.yml"]

# Files compose needs that nothing references, so the manifest below cannot derive
# them. .env is the one that matters: compose loads it from the project directory
# by convention, and it is where MENDER_IMAGE_TAG=main comes from. Without it the
# `${MENDER_IMAGE_TAG:-latest}` fallback applies and the suites quietly test
# `latest` images instead of `main`.
COMPOSE_EXTRAS = [".env"]

_INCLUDE_PATH = re.compile(r"^\s*-\s*path:\s*(\S+)", re.M)
_BIND_SRC = re.compile(r"^\s+-\s+(\./[A-Za-z0-9_./-]+):/", re.M)


def ref() -> str:
    text = (REPO / "src" / "mender_testkit" / "_server_ref.py").read_text()
    m = re.search(r'MENDER_SERVER_REF\s*=\s*"([0-9a-f]{40})"', text)
    if not m:
        raise SystemExit("no MENDER_SERVER_REF found in _server_ref.py")
    return m.group(1)


def checkout(sha: str, into: Path) -> None:
    subprocess.check_call(["git", "init", "-q", str(into)])
    subprocess.check_call(["git", "-C", str(into), "remote", "add", "origin", UPSTREAM])
    subprocess.check_call(
        ["git", "-C", str(into), "fetch", "-q", "--depth", "1", "origin", sha]
    )
    subprocess.check_call(["git", "-C", str(into), "checkout", "-q", "FETCH_HEAD"])


def compose_manifest(root: Path) -> list:
    """Every compose file and asset the roots reach, relative to `root`."""
    seen, queue = [], list(COMPOSE_ROOTS)
    while queue:
        rel = queue.pop(0)
        if rel in seen:
            continue
        seen.append(rel)
        text = (root / rel).read_text()
        base = Path(rel).parent
        for inc in _INCLUDE_PATH.findall(text):
            queue.append(str((base / inc) if inc.startswith(".") else Path(inc)))
        for src in _BIND_SRC.findall(text):
            target = root / src.lstrip("./")
            if target.is_dir():
                seen.extend(
                    str(p.relative_to(root)) for p in sorted(target.rglob("*")) if p.is_file()
                )
            elif target.is_file():
                seen.append(str(target.relative_to(root)))
    seen.extend(COMPOSE_EXTRAS)
    # Deduplicate, keeping order.
    out = []
    for p in seen:
        if p not in out:
            out.append(p)
    return out


def _namespace_imports(tree: Path) -> None:
    """Rewrite testutils' own absolute imports to the namespaced form.

    Upstream lives at backend/tests/testutils and imports itself as `testutils`.
    Here it sits inside this package, so those become mender_testkit.testutils.
    Done on vendoring rather than by hand, otherwise the next refresh silently
    reverts it.
    """
    for p in tree.rglob("*.py"):
        s = p.read_text()
        # Imports first, then any remaining dotted usage. Both are needed: an
        # unaliased `import testutils.util.crypto` binds the name `testutils`, so
        # rewriting only the import line rebinds it to `mender_testkit` and every
        # later `testutils.util.crypto.foo()` raises NameError. The lookbehind
        # keeps the already-rewritten imports from being rewritten twice.
        new = re.sub(
            r"^(\s*)(from|import) testutils\b",
            r"\1\2 mender_testkit.testutils",
            s,
            flags=re.M,
        )
        new = re.sub(r"(?<![.\w])testutils\.", "mender_testkit.testutils.", new)
        if new != s:
            p.write_text(new)


def materialise(src_root: Path, into: Path) -> None:
    if into.exists():
        shutil.rmtree(into)
    if TESTUTILS_DEST.exists():
        shutil.rmtree(TESTUTILS_DEST)
    shutil.copytree(src_root / TESTUTILS_SRC, TESTUTILS_DEST)
    for junk in TESTUTILS_DEST.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    _namespace_imports(TESTUTILS_DEST)
    for rel in compose_manifest(src_root):
        dest = into / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_root / rel, dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    sha = ref()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "mender-server"
        checkout(sha, work)

        if args.check:
            before = tempfile.mkdtemp()
            shutil.copytree(TESTUTILS_DEST, Path(before) / "testutils")
            shutil.copytree(COMPOSE_DEST, Path(before) / "compose")

        materialise(work, COMPOSE_DEST)

        if args.check:
            drift = []
            for name, current in (
                ("testutils", TESTUTILS_DEST),
                ("compose", COMPOSE_DEST),
            ):
                r = subprocess.run(
                    ["diff", "-r", str(Path(before) / name), str(current)],
                    capture_output=True,
                    text=True,
                )
                if r.returncode != 0:
                    drift.append(f"{name}:\n{r.stdout}")
            if drift:
                print(f"vendored trees differ from {sha[:8]}:\n" + "\n".join(drift))
                return 1
            print(f"vendored trees match {sha[:8]}")
            return 0

    files = sum(1 for _ in TESTUTILS_DEST.rglob("*.py"))
    compose = sum(1 for p in COMPOSE_DEST.rglob("*") if p.is_file())
    print(f"vendored {files} testutils files and {compose} compose files at {sha[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
