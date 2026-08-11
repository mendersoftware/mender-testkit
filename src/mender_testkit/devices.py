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
"""Bringing up client devices and finding them again.

The client compose project is per process rather than randomised, so the autouse
teardown of one xdist worker cannot take down another worker's device, and so a
leftover container is identifiable.
"""

import logging
import os
import subprocess
import time

from mender_testkit.testutils.infra.device import MenderDevice

from .docker import docker_lock
from .projects import server_network

logger = logging.getLogger(__name__)

project_name_client = "virtual_device" + os.environ.get(
    "PYTEST_XDIST_WORKER", str(os.getpid())
)

# Remembered from clients_up so that teardown resolves the same external network
# the clients were created with. Per process, so xdist workers cannot clobber each
# other's value.
client_network = None


def client_compose_env():
    """Environment a client compose file needs, for up and for down alike."""
    return {"MENDER_SERVER_NETWORK": client_network or server_network("os")}


class Env:
    """What a test fixture hands to a test: the server, and the devices."""

    def __init__(self):
        self.server = None
        self.devices = []
        self.device = None
        self.gateway = None
        self.auth = None

    def get_virtual_network_host_ip(self):
        container = f"{project_name_client}-mender-client-1"
        cmd = [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}",
            container,
        ]
        with docker_lock:
            output = subprocess.check_output(cmd)
        return output.decode().strip()


def clients_up(number_of_clients, compose_file, tenant_token=None, network=None):
    """Start `number_of_clients` clients and return them as MenderDevices.

    `network` selects which backend the clients attach to, so the same compose
    file serves both flavours. Remembered for teardown.
    """
    global client_network
    client_network = network or server_network("os")

    with docker_lock:
        cmd = [
            "docker",
            "compose",
            "-p",
            project_name_client,
            "-f",
            str(compose_file),
            "up",
            "-d",
            "--scale",
            f"mender-client={number_of_clients}",
        ]

        env = os.environ.copy()
        env["MENDER_SERVER_NETWORK"] = client_network
        if tenant_token:
            env["TENANT_TOKEN"] = tenant_token

        subprocess.check_call(cmd, env=env)

        clients = []
        for device_number in range(1, number_of_clients + 1):
            device = f"{project_name_client}-mender-client-{device_number}"
            client_ip = subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                    device,
                ],
                text=True,
            ).strip()
            clients.append(MenderDevice(f"{client_ip}:8822"))

    return clients


def clients_down(compose_file):
    with docker_lock:
        cmd = [
            "docker",
            "compose",
            "-p",
            project_name_client,
            "-f",
            str(compose_file),
            "down",
            "-v",
            "--remove-orphans",
        ]
        # check=False: teardown runs on the failure path too, where the project may
        # already be gone.
        subprocess.run(cmd, check=False, env={**os.environ, **client_compose_env()})


def wait_for_devices(env):
    # Give the device some time to start, so we don't get stuck in a 60 second ssh
    # exception right away.
    time.sleep(15)
    for device in env.devices:
        logger.info("waiting for '%s'", device.host)
        device.ssh_is_opened()


def get_mac_address(device):
    result = device.run(
        "/usr/share/mender/identity/mender-device-identity", hide=True, warn_only=True
    ).strip()
    return result.split("=")[-1]


def get_device_id(device, server):
    mac_address = get_mac_address(device)
    device_obj = next(
        d
        for d in server.get_accepted_devices()
        if d["identity_data"]["mac"] == mac_address
    )
    return device_obj["id"]
