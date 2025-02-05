#!/bin/bash -e
#
# Copyright 2021 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0

REALDIR=$(dirname $(readlink -f "$0"))
DIR=$(dirname $(realpath -se $0))
PDIRNAME=$(basename $(realpath -se $DIR/..))

if [ "$PDIRNAME" = "aws" ] || [ "$PDIRNAME" = "gce" ] || [ "$PDIRNAME" = "azure" ]; then
    TARGET="$PDIRNAME"
else
    echo "no target detected"
    exit 1
fi

docker build -f $REALDIR/Dockerfile_deb . -t scylladb/packer-builder-deb

DOCKER_ID=$(docker run -e AWS_SECRET_ACCESS_KEY -e AWS_ACCESS_KEY_ID -d  -v $HOME/.aws:/root/.aws -v `pwd`/../..:/scylla-machine-image scylladb/packer-builder-deb /bin/bash -c "cd /scylla-machine-image/; ./packer/build_image.sh --target $TARGET $*")

kill_it() {
    if [[ -n "$DOCKER_ID" ]]; then
        docker rm -f "$DOCKER_ID" > /dev/null 2>&1
        container=
    fi
}

trap kill_it SIGTERM SIGINT SIGHUP EXIT

docker logs "$DOCKER_ID" -f

if [[ -n "$DOCKER_ID" ]]; then
    exitcode="$(docker wait "$DOCKER_ID")"
else
    exitcode=99
fi

echo "Docker exitcode: $exitcode"

kill_it

trap - SIGTERM SIGINT SIGHUP EXIT

# after "docker kill", docker wait will not print anything
[[ -z "$exitcode" ]] && exitcode=1

docker run --rm \
    --entrypoint /bin/sh \
    -e HOST_UID=`id -u` \
    -v `pwd`:/ami \
    scylladb/packer-builder-deb \
    -c "chown -R `stat -c \"%u:%g\" $(pwd)` /ami/" || true

exit "$exitcode"

