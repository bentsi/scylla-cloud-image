#!/usr/bin/env python3
#
# Copyright 2020 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0

import sys
import logging
import pathlib


class ExitOnExceptionHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        # exit the application when logged message is above error logging level
        if record.levelno >= logging.ERROR:
            sys.exit(1)


def setup_logging(log_level=logging.INFO, log_dir_path="/var/lib/scylla/logs"):
    log_dir = pathlib.Path(log_dir_path)
    log_path = log_dir / "smi.log"

    log_dir.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    formatter = logging.Formatter("%(asctime)s - [%(module)s] - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(str(log_path))
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(ExitOnExceptionHandler())
    root_logger.setLevel(log_level)
