#
# Copyright 2022 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0
import logging
from email import message_from_string

import yaml

LOGGER = logging.getLogger(__name__)


class UserData:
    def __init__(self, *arg, **kwargs):
        self._instance_user_data = None
        self._cloud_instance = None

    @property
    def cloud_instance(self):
        if not self._cloud_instance:
            from lib.scylla_cloud import get_cloud_instance
            self._cloud_instance = get_cloud_instance()
        return self._cloud_instance

    @property
    def instance_user_data(self):
        if self._instance_user_data is None:
            try:
                raw_user_data = self.cloud_instance.user_data.strip()
                LOGGER.info("Got user-data: %s", raw_user_data)

                # Try reading mime multipart message, and extract
                # scylla-machine-image configuration out of it
                message = message_from_string(raw_user_data)
                if message.is_multipart():
                    for part in message.walk():
                        if part.get_content_type() in ('x-scylla/json', 'x-scylla/yaml'):
                            # we'll pick here the last seen json or yaml file,
                            # if multiple of them exists the last one wins, we are not merging them together
                            raw_user_data = part.get_payload()

                # try parse yaml, and fallback to parsing json
                self._instance_user_data = {}
                if raw_user_data:
                    self._instance_user_data = yaml.safe_load(raw_user_data)
                LOGGER.debug("parsed user-data: %s", self._instance_user_data)
            except Exception as e:
                LOGGER.warning("Error getting user data: %s. Will use defaults!", e)
                self._instance_user_data = {}
        return self._instance_user_data
