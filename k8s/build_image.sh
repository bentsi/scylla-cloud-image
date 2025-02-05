#!/bin/bash -e
#
# Copyright 2020 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0

CLOUD_PROVIDER=

print_usage() {
    echo "build_image.sh -c [aws]"
    echo "  -c cloud provider"
    exit 1
}
while getopts c: option
do
 case "${option}"
 in
 c) CLOUD_PROVIDER=${OPTARG};;
 *) print_usage;;
 esac
done

if [[ ! -e k8s/build_image.sh ]]; then
    echo "run build_image.sh in top of scylla-machine-image dir"
    exit 1
fi

echo "Building in $PWD..."

VERSION="k8s-${CLOUD_PROVIDER}-node-setup-0.0.2"
IMAGE_REF="scylladb/scylla-machine-image:${VERSION}"

docker build -f k8s/Dockerfile --build-arg "cloud_provider=${CLOUD_PROVIDER}" -t "${IMAGE_REF}" .
