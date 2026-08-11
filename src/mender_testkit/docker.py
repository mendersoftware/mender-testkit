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
"""Running docker compose, and the lock that serialises it."""

import logging
import os
import subprocess
import tempfile

import filelock

logger = logging.getLogger(__name__)

# Serialises docker operations across processes -- xdist workers, and separate
# suites on the same machine.
#
# Deliberately an absolute path, unlike the per-repo ".docker_lock" this replaces.
# A relative path is resolved against the working directory, so two suites started
# from different directories took two different locks and excluded nothing.
DOCKER_LOCK_PATH = os.environ.get("MENDER_DOCKER_LOCK") or os.path.join(
    tempfile.gettempdir(), "mender-docker.lock"
)

docker_lock = filelock.FileLock(DOCKER_LOCK_PATH)


def _compose_env(env):
    # None means "inherit", matching subprocess' own default.
    return None if env is None else {**os.environ, **env}


def docker_compose_start(project_name, files, cwd=None, env=None):
    with docker_lock:
        cmd = ["docker", "compose", "--project-name", project_name]
        for file in files:
            cmd.extend(["--file", str(file)])
        cmd += ["up", "--detach"]
        logger.debug("running %s", " ".join(cmd))
        subprocess.check_call(cmd, cwd=cwd, env=_compose_env(env))


def docker_compose_stop(project_name, files, cwd=None, env=None):
    with docker_lock:
        cmd = ["docker", "compose", "--project-name", project_name]
        for file in files:
            cmd.extend(["--file", str(file)])
        cmd += ["down", "--volumes", "--remove-orphans"]
        logger.debug("running %s", " ".join(cmd))
        subprocess.check_call(cmd, cwd=cwd, env=_compose_env(env))
