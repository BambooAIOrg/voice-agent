# GitHub Actions 部署指南 (私有仓库版)

本文档介绍如何使用GitHub Actions自动构建Docker镜像并部署到阿里云SAE，适用于私有GitHub仓库。

## 设置步骤

### 1. 创建GitHub App用于生成访问令牌

为了让SAE能访问私有的GitHub Container Registry镜像，需要创建GitHub App：

1. 前往GitHub账户设置 > Developer settings > GitHub Apps > New GitHub App
2. 设置App名称（如"SAE Deployment"）
3. 设置主页URL（可以是你的GitHub主页）
4. 取消勾选"Webhook active"
5. 在权限设置中，为"Contents"和"Packages"设置"Read-only"权限
6. 创建App后，生成私钥（Generate a private key）并下载
7. 记下App ID和安装ID

### 2. 在GitHub仓库中设置Secrets

在GitHub仓库的Settings > Secrets and variables > Actions中添加以下secrets：

- `ALIYUN_ACCESS_KEY_ID`: 阿里云访问密钥ID
- `ALIYUN_ACCESS_KEY_SECRET`: 阿里云访问密钥Secret
- `ALIYUN_SAE_APP_ID`: 在SAE创建的应用ID
- `ALIYUN_SAE_NAMESPACE_ID`: SAE命名空间ID
- `GH_APP_ID`: GitHub App的ID
- `GH_APP_PRIVATE_KEY`: GitHub App的私钥（整个文件内容）
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `ALIYUN_APPKEY`
- `MINIMAX_GROUP_ID`
- `MINIMAX_API_KEY`

### 3. 在阿里云SAE创建应用

1. 登录阿里云控制台，进入SAE服务
2. 切换到新加坡地区(ap-southeast-1)
3. 创建命名空间(需要关联VPC)，记下命名空间ID
4. 创建新应用：
   - 选择"镜像部署"
   - 镜像类型选择"公共镜像仓库"
   - 镜像地址填写：`ghcr.io/<你的GitHub用户名>/vocab-agent:latest`
   - **重要**：首次创建时无需担心私有镜像无法拉取，工作流会创建必要的镜像秘钥
5. 记下应用ID并添加到GitHub Secrets中的`ALIYUN_SAE_APP_ID`

### 4. 推送代码触发自动部署

将代码推送到GitHub仓库的master或main分支，自动触发构建和部署：

```bash
git add .
git commit -m "Update application"
git push origin master  # 或 git push origin main
```

也可以在GitHub仓库的Actions标签页手动触发工作流。

## 工作流程说明

这个GitHub Actions工作流程会：

1. 检出代码
2. 设置Docker Buildx
3. 登录到GitHub Container Registry (ghcr.io)
4. 构建并推送Docker镜像（作为私有镜像）
5. 创建GitHub访问令牌以供SAE拉取私有镜像
6. 在SAE中创建镜像拉取秘钥
7. 使用阿里云CLI更新SAE应用配置并部署最新镜像

## 故障排除

如果部署失败，可以在GitHub Actions日志中查看详细错误信息。常见问题：

1. **权限问题**：
   - 确保设置了正确的阿里云访问密钥并具有SAE操作权限
   - 检查GitHub App权限是否正确配置
   - 确保SAE命名空间ID正确

2. **镜像拉取问题**：
   - 检查SAE中是否成功创建了镜像拉取秘钥
   - 验证GitHub App的访问令牌是否生成成功

3. **应用ID错误**：验证`ALIYUN_SAE_APP_ID`是否正确

如需帮助，请检查GitHub Actions的运行日志和阿里云SAE控制台的应用日志。 