#
# Copyright 2020 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0
import sys
import logging
from unittest import TestCase
from pathlib import Path
import tempfile
import base64
import json

sys.path.append(str(Path(__file__).parent.parent))

from lib.log import setup_logging
from common.scylla_post_start import ScyllaMachineImagePostStart

from test_scylla_configure import DummyCloudInstance, TestScyllaConfigurator
LOGGER = logging.getLogger(__name__)


def b64(s):
    return base64.b64encode(s.encode()).decode()


class TestScyllaPostStart(TestCase):

    def setUp(self):
        LOGGER.info("Setting up test dir")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)
        setup_logging(log_level=logging.DEBUG, log_dir_path=str(self.temp_dir_path))
        LOGGER.info("Test dir: %s", self.temp_dir_path)
        self.post_start = ScyllaMachineImagePostStart()

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_scylla_post_start(self, user_data):
        self.post_start._cloud_instance = DummyCloudInstance(user_data=user_data, private_ipv4='127.0.0.1')
        self.post_start.run_post_start_script()

    def test_no_user_data(self):
        self.run_scylla_post_start('')

    def test_empty_script(self):
        self.run_scylla_post_start('{"post_start_script": ""}')

    def test_base64_encoding(self):
        self.run_scylla_post_start(json.dumps({"post_start_script": b64("echo start")}))

    def test_base64_encoding_error(self):
        with self.assertRaises(SystemExit):
            self.run_scylla_post_start(
                json.dumps({"post_start_script": b64("non-existing-command")}))

    def test_mime_multipart(self):
        scylla_user_data = {"post_start_script": b64("echo start")}
        for data_type in ('json', 'yaml'):
            msg = TestScyllaConfigurator.multipart_user_data(scylla_user_data, data_type)
            self.run_scylla_post_start(user_data=str(msg))
