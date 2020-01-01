#!/bin/bash -e

docker build  . -t scylladb/packer-builder

DOCKER_ID=$(docker run -e AWS_SECRET_ACCESS_KEY -e AWS_ACCESS_KEY_ID -d  -v $HOME/.aws:/root/.aws -v `pwd`:/ami scylladb/packer-builder /bin/bash -c "cd /ami ; bash ./build_ami.sh $*")

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
    scylladb/packer-builder \
    -c "chown -R `stat -c \"%u:%g\" $(pwd)` /ami/" || true

exit "$exitcode"

