FROM python:3.12-slim

WORKDIR /app

# 安装基础依赖和构建工具
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安装Poetry
RUN pip install poetry==1.5.1

# 复制项目文件
COPY pyproject.toml poetry.lock* ./
COPY README.md ./

# 配置Poetry不创建虚拟环境
RUN poetry config virtualenvs.create false

# 配置pip和Poetry使用阿里云镜像源
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
    && pip config set global.trusted-host mirrors.aliyun.com \
    && poetry config repositories.aliyun https://mirrors.aliyun.com/pypi/simple/ \
    && poetry config http-basic.aliyun "" ""

# 安装依赖 - 按批次安装以避免连接池问题
RUN poetry config installer.max-workers 1 && \
    poetry run pip install --upgrade pip && \
    poetry install --no-dev --no-interaction || \
    (poetry install --no-dev --no-interaction --no-ansi)

# 复制应用代码
COPY . .

# 启动命令
CMD ["python", "main.py", "start"] 