#!/bin/bash

set -e

IMAGE_NAME="jms_parse"
IMAGE_TAG="v1"
#### Mac
echo "准备编译 Mac 版本脚本"
bash -c "go build -o parse_darwin.so -buildmode=c-shared cmd/parse.go"
echo "Mac 版本脚本编译完成"

echo ""
echo "准备编译 Linux 版本脚本"
if docker images | grep -q "${IMAGE_NAME}[[:space:]]*${IMAGE_TAG}"; then
  echo "镜像 ${IMAGE_NAME}:${IMAGE_TAG} 已经存在，跳过构建镜像"
else
  echo "镜像不存在，先构建镜像!"
  bash -c "docker build -t jms_parse:v1 ."
fi
bash -c "docker run --rm -v $(pwd):/myapp jms_parse:v1 sh build_linux.sh"
echo "Linux 版本脚本编译完成"