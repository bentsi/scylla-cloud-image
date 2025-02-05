#!/bin/bash -e
#
# Copyright 2021 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0

. /etc/os-release

is_redhat() {
    [ -f /etc/redhat-release ]
}

is_debian() {
    [ -f /etc/debian_version ]
}

print_usage() {
    echo "build_deb.sh"
    echo "  no option available for this script."
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        *)
            print_usage
            ;;
    esac
done

apt_updated=false

# On clean Docker sudo command is not installed
if is_redhat && ! rpm -q sudo; then
    yum install -y sudo
elif is_debian && ! dpkg -s sudo > /dev/null 2>&1; then
    apt-get update
    apt_updated=true
    apt-get install -y sudo
fi

yum_install() {
    if ! rpm -q $1; then
        sudo yum install -y $1
    else
        echo "$1 already installed."
    fi
}

apt_install() {
    if ! dpkg -s $1 > /dev/null 2>&1; then
        if ! $apt_updated; then
            sudo apt-get update
            apt_updated=true
        fi
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y $1
    else
        echo "$1 already installed."
    fi
}

pkg_install() {
    if is_redhat; then
        yum_install $1
    elif is_debian; then
        apt_install ${1/-devel/-dev}
    fi
}

if [[ ! -e dist/debian/build_deb.sh ]]; then
    echo "run build_deb.sh in top of scylla-machine-image dir"
    exit 1
fi

pkg_install devscripts
pkg_install debhelper
pkg_install fakeroot
pkg_install dpkg-dev
pkg_install git
pkg_install python3
pkg_install python3-devel
pkg_install python3-pip

echo "Building in $PWD..."

VERSION=$(./SCYLLA-VERSION-GEN)
SCYLLA_VERSION=$(sed 's/-/~/' build/SCYLLA-VERSION-FILE)
SCYLLA_RELEASE=$(cat build/SCYLLA-RELEASE-FILE)
PRODUCT=$(cat build/SCYLLA-PRODUCT-FILE)
BUILDDIR=build/debian
PACKAGE_NAME="$PRODUCT-machine-image"

rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR"/scylla-machine-image

git archive --format=tar.gz HEAD -o "$BUILDDIR"/"$PACKAGE_NAME"_"$SCYLLA_VERSION"-"$SCYLLA_RELEASE".orig.tar.gz
cd "$BUILDDIR"/scylla-machine-image
tar -C ./ -xpf ../"$PACKAGE_NAME"_"$SCYLLA_VERSION"-"$SCYLLA_RELEASE".orig.tar.gz
cd -
./dist/debian/debian_files_gen.py
cd "$BUILDDIR"/scylla-machine-image
debuild -rfakeroot -us -uc
