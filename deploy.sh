#!/bin/bash

set -e

# 服务文件路径
SERVICE_FILE_PATH="/etc/systemd/system/voice_agent.service"

# 服务文件内容
SERVICE_FILE_CONTENT="[Unit]
Description=Voice Agent Service
After=network.target

[Service]
User=root
WorkingDirectory=/home/admin/agents
ExecStart=/home/admin/agents/.venv/bin/python main.py start
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=LIVEKIT_URL=${LIVEKIT_URL}
Environment=LIVEKIT_API_KEY=${LIVEKIT_API_KEY}
Environment=LIVEKIT_API_SECRET=${LIVEKIT_API_SECRET}
Environment=OPENAI_API_KEY=${OPENAI_API_KEY}
Environment=ALIYUN_ACCESS_KEY_ID=${ALIYUN_ACCESS_KEY_ID}
Environment=ALIYUN_ACCESS_KEY_SECRET=${ALIYUN_ACCESS_KEY_SECRET}
Environment=CARTESA_API_KEY=${CARTESA_API_KEY}
Environment=MINIMAX_GROUP_ID=${MINIMAX_GROUP_ID}
Environment=MINIMAX_API_KEY=${MINIMAX_API_KEY}
Environment=ALIYUN_LOG_ENDPOINT=${ALIYUN_LOG_ENDPOINT}
Environment=ALIYUN_LOG_ACCESSKEY_ID=${ALIYUN_LOG_ACCESSKEY_ID}
Environment=ALIYUN_LOG_ACCESSKEY_SECRET=${ALIYUN_LOG_ACCESSKEY_SECRET}
Environment=ALIYUN_LOG_PROJECT=${ALIYUN_LOG_PROJECT}
Environment=ALIYUN_LOG_STORE=${ALIYUN_LOG_STORE}
Environment=ALIYUN_LOG_FLUSH_INTERVAL=${ALIYUN_LOG_FLUSH_INTERVAL}
Environment=ALIYUN_LOG_BUFFER_SIZE=${ALIYUN_LOG_BUFFER_SIZE}
Environment=MYSQL_DATABASE_URI=${MYSQL_DATABASE_URI}
Environment=ENV=${ENV}
StandardOutput=journal+console
StandardError=journal+console
SyslogIdentifier=voice_agent

[Install]
WantedBy=multi-user.target"

# stop existing service
if systemctl is-active --quiet voice_agent.service; then
    sudo systemctl stop voice_agent.service || { echo "Failed to stop existing service"; exit 1; }
else
    echo "Service not running or not installed - proceeding with installation"
fi

# 更新 systemd 服务文件
echo "$SERVICE_FILE_CONTENT" | sudo tee $SERVICE_FILE_PATH || { echo "Failed to update service file"; exit 1; }

# 重新加载 systemd 配置
sudo systemctl daemon-reload || { echo "Failed to reload systemd configuration"; exit 1; }

# 进入项目目录
cd /home/admin/agents || { echo "Failed to change directory"; exit 1; }

# 安装 poetry（如果还没安装）
command -v poetry >/dev/null 2>&1 || { curl -sSL https://install.python-poetry.org | python3 - || { echo "Failed to install Poetry"; exit 1; }; }

# 配置 poetry 在项目目录下创建虚拟环境
export PATH="$HOME/.local/bin:$PATH"
poetry config virtualenvs.in-project true || { echo "Failed to configure Poetry"; exit 1; }

# 删除旧的虚拟环境（如果存在）
rm -rf .venv || { echo "Failed to remove old virtual environment"; exit 1; }

# 锁定依赖
echo "Locking dependencies..."
poetry lock >/dev/null 2>&1 || { echo "Failed to lock dependencies"; exit 1; }

# 使用 poetry 安装依赖
echo "Installing dependencies (this may take a while)..."
poetry install --only=main --quiet || { echo "Failed to install dependencies"; exit 1; }

# 尝试导入应用主模块
poetry run python -c "import main" || { echo "Failed to import main module"; exit 1; }

# 确保 python 可执行路径正确
chmod +x .venv/bin/python || { echo "Failed to set python executable permission"; exit 1; }

# 启动服务
sudo systemctl start voice_agent.service || { echo "Failed to start service"; exit 1; }

# 启用开机自启
sudo systemctl enable voice_agent.service || { echo "Failed to enable service"; exit 1; }

# 检查服务状态
sudo systemctl status voice_agent.service || { echo "Service is not active"; exit 1; }

# 等待15秒再检查服务是否正常运行
sleep 15

# 检查服务是否仍在运行
if systemctl is-active --quiet voice_agent.service; then
    echo "Voice Agent service is running successfully"
else
    echo "Voice Agent service failed to start properly"
    sudo journalctl -u voice_agent.service --no-pager -n 20
    exit 1
fi

echo "Voice Agent deployment completed successfully."