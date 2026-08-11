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
"""Compose project names, one per backend flavour.

Its own module so that server.py and devices.py can both use it without
importing each other.
"""

# A project of its own per flavour. Sharing one name means an enterprise test can
# silently end up talking to the OS stack, whichever came up first. Repos that
# only ever run one backend get "mender", which is the name they used to hardcode.
SERVER_PROJECTS = {
    "os": "mender",
    "enterprise": "mender_enterprise",
}


def server_project(plan):
    return SERVER_PROJECTS[plan]


def server_network(plan):
    """Name docker gives the network the backend's containers are attached to."""
    return f"{SERVER_PROJECTS[plan]}_default"
