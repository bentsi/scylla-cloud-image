#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 ScyllaDB
#

# SPDX-License-Identifier: AGPL-3.0

import string
import os
import shutil
import re
from pathlib import Path

class DebianFilesTemplate(string.Template):
    delimiter = '%'

scriptdir = os.path.dirname(__file__)

with open(os.path.join(scriptdir, 'changelog.template')) as f:
    changelog_template = f.read()

with open(os.path.join(scriptdir, 'control.template')) as f:
    control_template = f.read()

with open('build/SCYLLA-PRODUCT-FILE') as f:
    product = f.read().strip()

with open('build/SCYLLA-VERSION-FILE') as f:
    version = f.read().strip().replace('-', '~')
with open('build/SCYLLA-RELEASE-FILE') as f:
    release = f.read().strip()

if os.path.exists('build/debian/scylla-machine-image/debian'):
    shutil.rmtree('build/debian/scylla-machine-image/debian')
shutil.copytree('dist/debian/debian', 'build/debian/scylla-machine-image/debian')

if product != 'scylla':
    # Unlike other packages, scylla-machine-image is not relocatable package,
    # so we don't generate debian direcotry on build/debian/debian
    # to relocatable tar.gz
    for p in Path('build/debian/scylla-machine-image/debian').glob('scylla-*'):
        # pat1: scylla-server.service
        #    -> scylla-enterprise-server.scylla-server.service
        # pat2: scylla-server.scylla-fstrim.service
        #    -> scylla-enterprise-server.scylla-fstrim.service
        # pat3: scylla-conf.install
        #    -> scylla-enterprise-conf.install

        if m := re.match(r'^scylla(-[^.]+)\.service$', p.name):
            p.rename(p.parent / f'{p.name}')
        elif m := re.match(r'^scylla(-[^.]+\.scylla-[^.]+\.[^.]+)$', p.name):
            p.rename(p.parent / f'{product}{m.group(1)}')
        else:
            p.rename(p.parent / p.name.replace('scylla', product, 1))

s = DebianFilesTemplate(changelog_template)
changelog_applied = s.substitute(product=product, version=version, release=release, revision='1', codename='stable')

s = DebianFilesTemplate(control_template)
control_applied = s.substitute(product=product)

with open('build/debian/scylla-machine-image/debian/changelog', 'w') as f:
    f.write(changelog_applied)

with open('build/debian/scylla-machine-image/debian/control', 'w') as f:
    f.write(control_applied)
