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
"""The mender-server commit this package's vendored trees were taken from.

Both src/testutils/ and src/mender_testkit/data/mender_server/ are copies
of that commit, refreshed by scripts/vendor.py. Do not edit either tree by
hand: a fix belongs upstream in mender-server, after which this ref moves and
the copies are regenerated. Renovate updates the constant below, see
renovate.json5.

A commit rather than a release tag because the Host-header routing the tests
depend on (MENDER_HOSTNAME in docker-compose.yml) is not in any tag yet -- as of
this writing v4.1.1 through v4.1.3 have none of it.
"""

MENDER_SERVER_REF = "eb579b98c1060f6859de4b72e3c43dfcac00ddc9"
