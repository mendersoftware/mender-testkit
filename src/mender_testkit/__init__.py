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
"""Shared test infrastructure for the Mender integration test suites."""

import os

# Traefik's routers match on Host as well as path, and the tests address the
# ingress by container IP, so every request has to carry this. testutils defaults
# it to "traefik", the name mender-server's own deployments answer to.
#
# Set here rather than in plugin.py because it has to happen before
# testutils.api.client is imported -- that module reads it into a module-level
# constant. Importing any submodule of this package runs this file first, whereas
# plugin.py's own module-level imports already pull testutils in before its body
# executes.
os.environ.setdefault("GATEWAY_HOSTNAME", "docker.mender.io")

from ._server_ref import MENDER_SERVER_REF  # noqa: E402

__all__ = ["MENDER_SERVER_REF"]
