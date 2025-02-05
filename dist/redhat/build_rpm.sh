#!/bin/bash -e
#
# Copyright 2020 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0

. /etc/os-release

TARGET=

print_usage() {
    echo "build_rpm.sh -t [centos7/8|redhat]"
    echo "  -t target target distribution"
    exit 1
}
while getopts t:c: option
do
 case "${option}"
 in
 t) TARGET=${OPTARG};;
 *) print_usage;;
 esac
done



if [[ -n "${TARGET}" ]] ; then
  echo ${TARGET}
else
    echo "please provide valid target (-t)"
    exit 1
fi

if [[ ! -f /etc/redhat-release ]]; then
    echo "Need Redhat like OS to build RPM"
fi

# Centos8 is EOL, need to change mirrors
if [ "$VERSION" = "8" ] ; then
  sed -i 's/mirrorlist/#mirrorlist/g' /etc/yum.repos.d/CentOS-Linux-* ;
  sed -i 's|#baseurl=http://mirror.centos.org|baseurl=http://vault.centos.org|g' /etc/yum.repos.d/CentOS-Linux-* ;
fi

# On clean CentOS Docker sudo command is not installed
if ! rpm -q sudo; then
    yum install -y sudo
fi


pkg_install() {
    if ! rpm -q $1; then
        sudo yum install -y $1
    else
        echo "$1 already installed."
    fi
}

if [[ ! -e dist/redhat/build_rpm.sh ]]; then
    echo "run build_rpm.sh in top of scylla-machine-image dir"
    exit 1
fi

pkg_install rpm-build
pkg_install git
pkg_install python3

echo "Building in $PWD..."

VERSION=$(./SCYLLA-VERSION-GEN)
SCYLLA_VERSION=$(sed 's/-/~/' build/SCYLLA-VERSION-FILE)
SCYLLA_RELEASE=$(cat build/SCYLLA-RELEASE-FILE)
PRODUCT=$(cat build/SCYLLA-PRODUCT-FILE)

PACKAGE_NAME="$PRODUCT-machine-image"

RPMBUILD=$(readlink -f build/)
mkdir -pv ${RPMBUILD}/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

git archive --format=tar --prefix=$PACKAGE_NAME-$SCYLLA_VERSION/ HEAD -o $RPMBUILD/SOURCES/$PACKAGE_NAME-$SCYLLA_VERSION-$SCYLLA_RELEASE.tar
cp dist/redhat/scylla-machine-image.spec $RPMBUILD/SPECS/$PACKAGE_NAME.spec

parameters=(
    -D"product $PRODUCT"
    -D"version $SCYLLA_VERSION"
    -D"release $SCYLLA_RELEASE"
    -D"package_name $PACKAGE_NAME"
    -D"scylla true"
)

if [[ "$TARGET" = "centos7" ]] || [[ "$TARGET" = "centos8" ]]; then
    rpmbuild "${parameters[@]}" -ba --define '_binary_payload w2.xzdio' --define "_topdir $RPMBUILD" --define "dist .el7" $RPM_JOBS_OPTS $RPMBUILD/SPECS/$PACKAGE_NAME.spec
else
    rpmbuild "${parameters[@]}" -ba --define '_binary_payload w2.xzdio' --define "_topdir $RPMBUILD" $RPM_JOBS_OPTS $RPMBUILD/SPECS/$PACKAGE_NAME.spec
fi
