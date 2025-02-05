#!/bin/bash -e
#
# Copyright 2021 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0

DIR=$(dirname $(readlink -f "$0"))
source "$DIR"/../SCYLLA-VERSION-GEN

CREATION_TIMESTAMP=$(date -u '+%FT%H-%M-%S')
OPERATING_SYSTEM="ubuntu24.04"
EXIT_STATUS=0
DRY_RUN=false
DEBUG=false
BUILD_MODE='release'
TARGET=
ENV_TAG="debug"

print_usage() {
    echo "$0 --repo [URL] --target [distribution]"
    echo "  --repo                  Repository for both install and update, specify .repo/.list file URL"
    echo "  --repo-for-install      Repository for install, specify .repo/.list file URL"
    echo "  --repo-for-update       Repository for update, specify .repo/.list file URL"
    echo "  [--product]             scylla or scylla-enterprise, default from SCYLLA-PRODUCT-FILE"
    echo "  [--dry-run]             Validate template only (image is not built). Default: false"
    echo "  [--scylla-build-sha-id] Scylla build SHA id form metadata file"
    echo "  [--branch]              Set the release branch for GCE label. Default: master"
    echo "  [--ami-regions]         Set regions to copy the AMI when done building it (including permissions and tags)"
    echo "  [--build-tag]           Jenkins Build tag"
    echo "  [--env-tag]             Environment tag for our images. default: debug. Valid options: daily(master)|candidate(releases)|production(releases)|private(custom images for customers)"
    echo "  [--build-mode]          Choose which build mode to use for Scylla installation. Default: release. Valid options: release|debug"
    echo "  [--debug]               Build debug image with special prefix for image name. Default: false."
    echo "  [--log-file]            Path for log. Default build/ami.log on current dir. Default: build/packer.log"
    echo "  --target                Target cloud (aws/gce/azure), mandatory when using this script directly, and not by soft links"
    echo "  --arch                  Set the image build architecture. Valid options: x86_64 | aarch64 . if use didn't pass this parameter it will use local node architecture"
    echo "  --ec2-instance-type     Set EC2 instance type to use while building the AMI. If empty will use defaults per architecture"
    exit 1
}
PACKER_SUB_CMD="build"
REPO_FOR_INSTALL=
PACKER_LOG_PATH=build/packer.log

while [ $# -gt 0 ]; do
    case "$1" in
        "--repo")
            REPO_FOR_INSTALL="https://$2"
            echo "--repo parameter: REPO_FOR_INSTALL $REPO_FOR_INSTALL"
            INSTALL_ARGS="$INSTALL_ARGS --repo https://$2"
            shift 2
            ;;
        "--repo-for-install")
            REPO_FOR_INSTALL=$2
            echo "--repo-for-install parameter: REPO_FOR_INSTALL $REPO_FOR_INSTALL"
            INSTALL_ARGS="$INSTALL_ARGS --repo-for-install $2"
            shift 2
            ;;
        "--repo-for-update")
            echo "--repo-for-update parameter: |$2|"
            INSTALL_ARGS="$INSTALL_ARGS --repo-for-update $2"
            shift 2
            ;;
        "--product")
            PRODUCT=$2
            echo "--product parameter: PRODUCT |$PRODUCT|"
            shift 2
            ;;
        "--scylla-build-sha-id")
            SCYLLA_BUILD_SHA_ID=$2
            echo "--scylla-build-sha-id parameter: SCYLLA_BUILD_SHA_ID |$SCYLLA_BUILD_SHA_ID|"
            shift 2
            ;;
        "--build-tag")
            BUILD_TAG=$2
            echo "--build-tag parameter: BUILD_TAG |$BUILD_TAG|"
            shift 2
            ;;
        "--env-tag")
            ENV_TAG=$2
            echo "--env-tag parameter: ENV_TAG |$ENV_TAG|"
            shift 2
            ;;
        "--version")
            VERSION=$2
            echo "--version: VERSION |$VERSION|"
            shift 2
            ;;
        "--scylla-release")
            SCYLLA_RELEASE=$2
            echo "--scylla-release: SCYLLA_RELEASE |$SCYLLA_RELEASE|"
            shift 2
            ;;
        "--scylla-machine-image-release")
            SCYLLA_MACHINE_IMAGE_RELEASE=$2
            echo "--scylla-machine-image-release: SCYLLA_MACHINE_IMAGE_RELEASE |$SCYLLA_MACHINE_IMAGE_RELEASE|"
            shift 2
            ;;
        "--branch")
            BRANCH=$2
            echo "--branch parameter: BRANCH |$BRANCH|"
            shift 2
            ;;
        "--ami-regions"):
            AMI_REGIONS=$2
            echo "--ami-regions parameter: AMI_REGIONS |$AMI_REGIONS|"
            shift 2
            ;;
        "--log-file")
            PACKER_LOG_PATH=$2
            echo "--log-file parameter: PACKER_LOG_PATH |$PACKER_LOG_PATH|"
            shift 2
            ;;
        "--build-mode")
            BUILD_MODE=$2
            shift 2
            ;;
        "--debug")
            echo "!!! Building image for debug !!!"
            DEBUG=true
            shift 1
            ;;
        "--dry-run")
            echo "!!! Running in DRY-RUN mode !!!"
            PACKER_SUB_CMD="validate"
            DRY_RUN=true
            shift 1
            ;;
        "--target")
            TARGET="$2"
            shift 2
            echo "--target parameter TARGET: |$TARGET|"
            case "$TARGET" in
              "aws")
                JSON_FILE="ami_variables.json"
                ;;
              "gce")
                JSON_FILE="gce_variables.json"
                ;;
              "azure")
                JSON_FILE="azure_variables.json"
                ;;
              *)
                print_usage
                ;;
            esac
            ;;
        "--arch")
            ARCH="$2"
            shift 2
            ;;
        "--ec2-instance-type")
            INSTANCE_TYPE="$2"
            shift 2
            ;;
        *)
            echo "ERROR: Illegal option: $1"
            print_usage
            ;;
    esac
done

if [ -z "$PRODUCT" ]; then
    PRODUCT=$(cat build/SCYLLA-PRODUCT-FILE)
fi
INSTALL_ARGS="$INSTALL_ARGS --product $PRODUCT"

echo "INSTALL_ARGS: |$INSTALL_ARGS|"

if [ -z "$TARGET" ]; then
    echo "Missing --target parameter. Please specify target cloud (aws/gce/azure)"
    exit 1
fi

SSH_USERNAME=ubuntu

SCYLLA_FULL_VERSION="$VERSION-$SCYLLA_RELEASE"
SCYLLA_MACHINE_IMAGE_VERSION="$VERSION-$SCYLLA_MACHINE_IMAGE_RELEASE"

if [ -z "$REPO_FOR_INSTALL" ]; then
    echo "ERROR: No --repo or --repo-for-install were given."
    print_usage
    exit 1
fi

if [ "$TARGET" = "aws" ]; then

    SSH_USERNAME=ubuntu
    SOURCE_AMI_OWNER=099720109477
    REGION=us-east-1

    arch="$ARCH"
    case "$arch" in
      "x86_64")
        SOURCE_AMI_FILTER="ubuntu-minimal/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64*"
        if [ -z "$INSTANCE_TYPE" ]; then
          INSTANCE_TYPE="c4.xlarge"
        fi
        ;;
      "aarch64")
        SOURCE_AMI_FILTER="ubuntu-minimal/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64*"
        if [ -z "$INSTANCE_TYPE" ]; then
          INSTANCE_TYPE="im4gn.2xlarge"
        fi
        ;;
      *)
        echo "Unsupported architecture: $arch"
        exit 1
    esac

    SCYLLA_AMI_DESCRIPTION="scylla-$SCYLLA_FULL_VERSION scylla-machine-image-$SCYLLA_MACHINE_IMAGE_VERSION scylla-python3-$SCYLLA_FULL_VERSION"

    PACKER_ARGS+=(-var region="$REGION")
    PACKER_ARGS+=(-var buildMode="$BUILD_MODE")
    PACKER_ARGS+=(-var instance_type="$INSTANCE_TYPE")
    PACKER_ARGS+=(-var source_ami_filter="$SOURCE_AMI_FILTER")
    PACKER_ARGS+=(-var source_ami_owner="$SOURCE_AMI_OWNER")
    PACKER_ARGS+=(-var scylla_ami_description="${SCYLLA_AMI_DESCRIPTION:0:255}")
elif [ "$TARGET" = "gce" ]; then
    SSH_USERNAME=ubuntu
    SOURCE_IMAGE_FAMILY="ubuntu-minimal-2404-lts-amd64"

    PACKER_ARGS+=(-var source_image_family="$SOURCE_IMAGE_FAMILY")
elif [ "$TARGET" = "azure" ]; then
    REGION="EAST US"
    SSH_USERNAME=azureuser
    SCYLLA_IMAGE_DESCRIPTION="scylla-$SCYLLA_FULL_VERSION scylla-machine-image-$SCYLLA_MACHINE_IMAGE_VERSION scylla-python3-$SCYLLA_FULL_VERSION"

    PACKER_ARGS+=(-var scylla_image_description="${SCYLLA_IMAGE_DESCRIPTION:0:255}")
    PACKER_ARGS+=(-var client_id="$AZURE_CLIENT_ID")
    PACKER_ARGS+=(-var client_secret="$AZURE_CLIENT_SECRET")
    PACKER_ARGS+=(-var tenant_id="$AZURE_TENANT_ID")
    PACKER_ARGS+=(-var subscription_id="$AZURE_SUBSCRIPTION_ID")
fi

if [ "$TARGET" = "azure" ]; then
  if [ "$BUILD_MODE" = "debug" ]; then
    IMAGE_NAME="scylla-debug-$VERSION-$ARCH-$(date '+%FT%T')"
  else
    IMAGE_NAME="scylla-$VERSION-$ARCH-$(date '+%FT%T')"
  fi
else
  IMAGE_NAME="$PRODUCT-$VERSION-$ARCH-$(date '+%FT%T')"
fi
if [ "$BUILD_MODE" = "debug" ]; then
  IMAGE_NAME="$PRODUCT-debug-$VERSION-$ARCH-$(date '+%FT%T')"
fi
if $DEBUG ; then
  IMAGE_NAME="debug-$IMAGE_NAME"
fi

if [ ! -f $JSON_FILE ]; then
    echo "'$JSON_FILE not found. Please create it before start building Image."
    echo "See variables.json.example"
    exit 1
fi

mkdir -p build

export PACKER_LOG=1
export PACKER_LOG_PATH

set -x
/usr/bin/packer ${PACKER_SUB_CMD} \
  -only="$TARGET" \
  -var-file="$JSON_FILE" \
  -var install_args="$INSTALL_ARGS" \
  -var ssh_username="$SSH_USERNAME" \
  -var scylla_full_version="$SCYLLA_FULL_VERSION" \
  -var scylla_version="$VERSION" \
  -var scylla_machine_image_version="$SCYLLA_MACHINE_IMAGE_VERSION" \
  -var scylla_python3_version="$SCYLLA_FULL_VERSION" \
  -var creation_timestamp="$CREATION_TIMESTAMP" \
  -var scylla_build_sha_id="$SCYLLA_BUILD_SHA_ID" \
  -var build_tag="$BUILD_TAG" \
  -var environment="$ENV_TAG" \
  -var operating_system="$OPERATING_SYSTEM" \
  -var branch="$BRANCH" \
  -var ami_regions="$AMI_REGIONS" \
  -var arch="$ARCH" \
  -var product="$PRODUCT" \
  -var build_mode="$BUILD_MODE" \
  -var image_name="$IMAGE_NAME" \
  "${PACKER_ARGS[@]}" \
  "$DIR"/scylla.json
set +x
# For some errors packer gives a success status even if fails.
# Search log for errors
if $DRY_RUN ; then
  echo "DryRun: No need to grep errors on log"
else
  GREP_STATUS=0
  case "$TARGET" in
    "aws")
      grep "us-east-1:" $PACKER_LOG_PATH
      GREP_STATUS=$?
      ;;
    "gce")
      grep "A disk image was created" $PACKER_LOG_PATH
      GREP_STATUS=$?
      ;;
    "azure")
      grep "Builds finished. The artifacts of successful builds are:" $PACKER_LOG_PATH
      GREP_STATUS=$?
      ;;
    *)
      echo "No Target is defined"
      exit 1
  esac

  if [ $GREP_STATUS -ne 0 ] ; then
    echo "Error: No image line found on log."
    exit 1
  else
    echo "Success: image line found on log"
  fi
fi

exit $EXIT_STATUS
