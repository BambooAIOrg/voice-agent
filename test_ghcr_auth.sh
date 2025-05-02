#!/bin/bash
set -e

# 模拟工作流中的行为
echo "请输入GitHub Token (输入时不会显示):"
read -s GITHUB_TOKEN

USERNAME="BambooAIOrg"
echo "使用用户名: $USERNAME 和提供的Token测试"

# 生成与工作流中相同格式的认证字符串
AUTH_STRING=$(echo -n "$USERNAME:$GITHUB_TOKEN" | base64 | tr -d '\n')
echo "已生成认证字符串"

# 创建与工作流中相同格式的Docker配置
DOCKER_CONFIG="{\"auths\":{\"ghcr.io\":{\"username\":\"$USERNAME\",\"password\":\"$GITHUB_TOKEN\",\"auth\":\"$AUTH_STRING\"}}}"
echo "已创建Docker配置"

# 将配置写入临时文件
CONFIG_FILE=~/.docker/config.json.backup
if [ -f ~/.docker/config.json ]; then
  echo "备份现有Docker配置..."
  cp ~/.docker/config.json $CONFIG_FILE
fi

echo "写入测试配置..."
mkdir -p ~/.docker
echo $DOCKER_CONFIG > ~/.docker/config.json

echo "尝试拉取镜像..."
# 尝试直接拉取，使用配置文件中的认证信息
IMAGE="ghcr.io/$USERNAME/vocab-agent:latest"
if docker pull $IMAGE; then
  echo "镜像拉取成功！认证信息有效。"
else
  echo "镜像拉取失败。可能是认证信息无效或镜像不存在。"
fi

# 恢复原始配置
if [ -f $CONFIG_FILE ]; then
  echo "恢复原始Docker配置..."
  mv $CONFIG_FILE ~/.docker/config.json
else
  echo "删除测试配置..."
  rm ~/.docker/config.json
fi 