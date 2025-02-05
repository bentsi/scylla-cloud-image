#!/usr/bin/env python3
#
# Copyright 2021 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0

import base64
import logging
import pathlib
import subprocess
import sys

from lib.log import setup_logging
from lib.user_data import UserData
from lib.scylla_cloud import scylla_excepthook

LOGGER = logging.getLogger(__name__)
DISABLE_FILE_PATH = '/etc/scylla/machine_image_post_start_configured'


class ScyllaMachineImagePostStart(UserData):
    def run_post_start_script(self):
        post_start_script = self.instance_user_data.get("post_start_script")
        if post_start_script:
            try:
                decoded_script = base64.b64decode(post_start_script)
                LOGGER.info(f"Running post start script:\n{decoded_script}")
                subprocess.run(decoded_script, check=True, shell=True, timeout=600)
                return True
            except Exception as e:
                scylla_excepthook(*sys.exc_info())
                LOGGER.error(f"Post start script failed: {e}")
                sys.exit(1)


if __name__ == "__main__":
    setup_logging()
    init = ScyllaMachineImagePostStart()
    if init.run_post_start_script():
        pathlib.Path(DISABLE_FILE_PATH).touch()
