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
"""pytest plugin: backend lifecycle fixtures.

Registered through the pytest11 entry point, so it loads before any conftest --
which is also what gets GATEWAY_HOSTNAME set in time, see this package's
__init__.

Replaces four hand-rolled copies of the same fixtures. Two behaviours the copies
had between them are both kept here:

  * the backend starts once per session however many xdist workers there are,
    coordinated through a lock and a refcount in the shared tmp directory. A
    session-scoped fixture runs once *per worker*, so both ends need
    cross-process agreement: the first worker in starts it, every worker waits
    until it answers, and only the last worker out tears it down and cleans up.

  * only one flavour runs at a time. Two full backends plus QEMU clients starve
    the Go services of CPU and requests start coming back from Traefik as 504s.
    Switching costs a restart, which is cheaper than the contention.
"""

import json
import logging
import os
import time

import filelock
import pytest

from .compose import compose_files
from .docker import docker_compose_start, docker_compose_stop
from .projects import SERVER_PROJECTS
from .server import wait_for_backend_ready

logger = logging.getLogger(__name__)


class _Backends:
    """Keeps exactly one backend flavour running, refcounted across processes.

    Two counters, because they answer different questions:

      workers  how many pytest sessions are attached. The first one in starts a
               backend, the last one out stops it and cleans up. This is the
               refcount the per-repo fixtures already used, and it is what makes
               xdist safe: a worker finishing early means nothing, because xdist
               hands out tests dynamically and the others are still running.

      tests    how many tests hold the backend right now. Zero means the flavour
               can be switched. Needed only because these fixtures are
               function-scoped, which is what lets a session span both flavours.

    Conflating them breaks one case or the other: `tests` reaches zero between
    every test, so tearing down there restarts the stack constantly; `workers`
    reaches zero only at the very end, so switching on it never happens.

    Every worker takes part in both counters, and any of them may start or stop
    the stack -- the lock decides who gets there first. There is deliberately no
    designated owner worker.
    """

    # How long to wait for the other flavour to drain before giving up.
    switch_timeout = 600

    def __init__(self, shared_dir):
        self.lock = filelock.FileLock(str(shared_dir / "mender-backend.lock"))
        self.state_file = shared_dir / "mender-backend.json"

    def _read(self):
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {"current": None, "tests": 0, "workers": 0}

    def _write(self, state):
        self.state_file.write_text(json.dumps(state))

    def attach(self):
        with self.lock:
            state = self._read()
            state["workers"] += 1
            self._write(state)

    def detach(self):
        """Last session out stops whatever is running."""
        with self.lock:
            state = self._read()
            state["workers"] = max(0, state["workers"] - 1)
            if state["workers"] == 0 and state["current"] is not None:
                self._stop(state["current"])
                state["current"], state["tests"] = None, 0
            self._write(state)

    def acquire(self, plan):
        project = SERVER_PROJECTS[plan]
        deadline = time.monotonic() + self.switch_timeout
        while True:
            with self.lock:
                state = self._read()
                if state["current"] == plan:
                    state["tests"] += 1
                    self._write(state)
                    break
                if state["tests"] == 0:
                    if state["current"] is not None:
                        self._stop(state["current"])
                    logger.info("starting the %s backend", plan)
                    docker_compose_start(
                        project_name=project, files=compose_files(plan)
                    )
                    state["current"], state["tests"] = plan, 1
                    self._write(state)
                    break
                other, held = state["current"], state["tests"]

            # Another worker is mid-test on the other flavour. Standing both up is
            # what starves the Go services and turns requests into 504s, so wait
            # for it to drain instead. A worker never holds two flavours at once --
            # these fixtures are function-scoped -- so this always resolves.
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"timed out after {self.switch_timeout}s waiting for the "
                    f"{other} backend to be released by {held} test(s) before "
                    f"switching to {plan}"
                )
            logger.info(
                "waiting for the %s backend to be released by %d test(s)", other, held
            )
            time.sleep(2)

        # Outside the lock, so workers wait concurrently rather than one at a time.
        wait_for_backend_ready(project)

    def release(self, plan):
        with self.lock:
            state = self._read()
            state["tests"] = max(0, state["tests"] - 1)
            self._write(state)

    def _stop(self, plan):
        logger.info("stopping the %s backend", plan)
        docker_compose_stop(
            project_name=SERVER_PROJECTS[plan], files=compose_files(plan)
        )


@pytest.fixture(scope="session")
def mender_backends(tmp_path_factory):
    """Session-wide backend manager. Not usually used directly."""
    # getbasetemp() is per worker; its parent is shared by every worker of the run.
    shared = tmp_path_factory.getbasetemp().parent
    backends = _Backends(shared)
    backends.attach()
    yield backends
    backends.detach()


def _backend_fixture(plan):
    # Function-scoped on purpose. A session-scoped fixture is set up once, so a
    # session whose tests want different flavours would keep whichever came up
    # first and quietly run the rest against it.
    @pytest.fixture(scope="function")
    def _fixture(mender_backends):
        mender_backends.acquire(plan)
        yield
        mender_backends.release(plan)

    return _fixture


os_backend_server = _backend_fixture("os")
enterprise_backend_server = _backend_fixture("enterprise")
