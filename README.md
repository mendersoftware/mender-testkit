# mender-testkit

Shared test infrastructure for the Mender integration test suites.

The suites in `mender-binary-delta`, `mender-configure-module`, `mender-gateway`,
`mender-orchestrator` and `integration` all rely on the same things: a mender-server
backend brought up under docker compose, a client for its management API, and a
way to start QEMU devices against it. Each repo used to carry its own copy of all
of it, kept in step by hand, plus a `mender_server` submodule for the compose
files. This package is that copy.

## Install
```
pip install mender-testkit
```

That replaces both the `mender_server` submodule and the
`pip install -r mender_server/backend/tests/requirements-integration.txt` line
that every consuming repo used to have -- the dependency list is this package's
own.

`kubernetes` is an extra rather than a dependency. Nothing here imports it unless
`K8S` is set in the environment, so a suite running against docker compose does
not need it installed:

```
pip install mender-testkit[kubernetes]     # only if you run against a cluster
```

## Using it

**The backend.** Request one of two pytest fixtures and it is up before your test
runs. They arrive through an entry point, so there is nothing to import or
register:

```python
def test_something(os_backend_server):
    server = Server()                      # plan="os"

def test_something_else(enterprise_backend_server):
    server = Server(plan="enterprise")     # provisions a tenant via tenantadm
```

One backend runs at a time. Two full stacks plus QEMU clients starve the Go
services of CPU and requests start coming back from Traefik as 504s, so asking
for the other flavour switches rather than adding. Under `pytest-xdist` the stack
is started once for the whole run and torn down when the last worker finishes.

**The API.** `Server` is a client, not a lifecycle manager -- it assumes the
backend is already up:

```python
from mender_testkit.server import Server

server = Server(plan="enterprise")
device_ids = server.accept_devices(env.devices)
server.upload_image("artifact.mender")
deployment = server.create_deployment("artifact.mender", device_ids)
server.check_expected_status("finished", deployment)
```

Every request carries `Host: docker.mender.io`, because Traefik's routers match on
Host as well as path and the tests reach it by container IP. `GATEWAY_HOSTNAME`
is set when this package is first imported; override it in the environment if your
ingress answers to something else.

**Devices.**

```python
from mender_testkit.devices import Env, clients_up, wait_for_devices

env = Env()
env.server = Server()
env.devices = clients_up(2, "docker-compose.client.yml", network=env.server.network)
wait_for_devices(env)
```

Client compose files stay in the consuming repo: the device under test is the
repo's product, not this package's business. What this package supplies is the
network it attaches to, via `MENDER_SERVER_NETWORK`, which `clients_up` exports.
Declare it in your client compose file as

```yaml
networks:
  mender_server:
    external: true
    name: ${MENDER_SERVER_NETWORK:-mender_default}
```

**Compose files, directly.** If you drive compose yourself rather than through the
fixtures:

```python
from mender_testkit.compose import compose_dir, compose_files

files = compose_files("enterprise")        # absolute paths, in -f order
```

They are package data, so they are copied to a real directory on first use --
compose needs actual files, and it needs the whole tree, because
`docker-compose.yml` bind-mounts `./compose/certs` and `./compose/config` relative
to the project directory. Pass `compose_dir()` as `--project-directory`. It is a
temporary directory removed at process exit; pass `compose_dir(dest=...)` if you
need one that outlives the process.

By default the backend publishes no host ports. The tests reach Traefik by
container IP, so publishing buys nothing and costs exclusivity -- only one stack
can hold 443. Pass `publish_ports=True` if you want to reach the backend from the
host, which works for one backend at a time.

## The vendored trees

Two directories are **generated, not written**:

| path | from |
| --- | --- |
| `src/mender_testkit/testutils/` | mender-server's `backend/tests/testutils` |
| `src/mender_testkit/data/mender_server/` | mender-server's compose files |

Both are copies of the commit in `src/mender_testkit/_server_ref.py`, produced by
`scripts/vendor.py`. Do not edit either by hand: a fix belongs upstream in
mender-server, after which the ref moves and the copies are regenerated. Editing
them here creates a fork that looks identical to a stale one, which is the state
this package exists to end.

`testutils` is vendored rather than depended on because mender-server does not
publish it. Committing the copies rather than fetching at build time keeps the
wheel reproducible from a tag and lets `pip install` work without reaching
GitHub.

To refresh:

```
$EDITOR src/mender_testkit/_server_ref.py     # or let Renovate do it
scripts/vendor.py
scripts/vendor.py --check                     # asserts the trees match the ref
```

`--check` is worth running in CI: it catches both a hand-edit and a ref bump whose
files were never regenerated.

### Why a commit and not a release tag

Because these suites test unreleased server code. `.env` pins the backend images
to `main`, and the clients they run against are `client-main` builds, so the
compose files and `testutils` have to come from the same place -- a release tag
would mean a released compose driving unreleased images.

The immediate reason is narrower: fixes these suites need land on `main` first and
reach a tag only at the next release, so a tag-based pin is always some way behind
what the tests require.

A tag is otherwise perfectly workable. Tracking released versions instead would
mean putting a tag in `_server_ref.py`, swapping this file's manager to the
`github-releases` datasource (matching `currentValue` rather than
`currentDigest`), and teaching `scripts/vendor.py` to fetch a tag rather than a
SHA. Note that release tags route on path alone; the `Host(...)` clause matching
`MENDER_HOSTNAME` is something `main` *added*, so the explicit `Host` header this
package sends is required by `main` and merely redundant against a tag.

### Judging a ref bump

mender-server moves at roughly 280 commits a month, so most bumps change nothing
here. What matters is whether the files these suites actually consume moved:

```
git diff <old>..<new> -- docker-compose.yml compose/docker-compose.enterprise.yml \
                         compose/config compose/certs
```

Empty or cosmetic, and one suite is enough to gate it. If the service list moved,
run them all. A 1699-commit bump once turned out to be nine lines of image tags.

## Building

```
rm -rf build dist src/*.egg-info
python -m build --wheel
```

The `rm` is needed here because setuptools reuses `build/lib`, and after
`testutils` moved under `mender_testkit/`, a stale copy there produced a wheel
containing the tree *twice* -- once at top level, once namespaced -- with no
warning. Verify what you built:

```
python -c "import zipfile,glob; \
  print([n for n in zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[-1]).namelist() \
         if n.startswith('testutils/')])"     # must be empty
```
