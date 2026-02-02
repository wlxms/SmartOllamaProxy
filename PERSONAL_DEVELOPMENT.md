# 个人开发分支使用指南

本文档介绍如何在 `personal-dev` 分支上使用您个人的 API 密钥进行开发，同时保持 `config.yaml` 文件的机密信息安全。

## 分支状态

当前您位于 `personal-dev` 分支，该分支基于 `main` 分支创建，并进行了以下增强：

1. **环境变量支持**：API 密钥现在可以从环境变量加载，优先于配置文件
2. **`.env` 文件支持**：自动加载 `.env` 文件中的环境变量
3. **安全配置**：`.gitignore` 已更新，忽略敏感文件

## 快速开始

### 1. 复制环境变量模板

```bash
# 复制模板文件（不要在版本控制中提交 .env）
cp .env.example .env
```

### 2. 编辑 .env 文件

用您自己的 API 密钥替换 `.env` 文件中的占位符：

```env
# DeepSeek API 密钥
DEEPSEEK_API_KEY=sk-your-real-deepseek-api-key-here

# 硅基流动 API 密钥
SILICONFLOW_API_KEY=sk-your-real-siliconflow-api-key-here

# 通义千问 API 密钥
QWEN_API_KEY=sk-your-real-qwen-api-key-here

# 通义千问 Coder 订阅 API 密钥
QWEN_CODER_API_KEY=sk-your-real-qwen-coder-api-key-here
```

### 3. 启动代理服务

#### 方式一：直接运行（自动加载 .env）
```bash
python main.py
```

#### 方式二：使用 uvicorn
```bash
uvicorn main:app --host 0.0.0.0 --port 11435 --reload
```

## 环境变量工作原理

### 自动加载
- 应用启动时会自动加载 `.env` 文件（如果存在）
- 环境变量优先于 `config.yaml` 中的配置

### 变量命名规则
环境变量名称根据模型组自动生成：
- `deepseek` → `DEEPSEEK_API_KEY`
- `siliconflow` → `SILICONFLOW_API_KEY`
- `qwen` → `QWEN_API_KEY`
- `qwen-coder` → `QWEN_CODER_API_KEY`

### 优先级顺序
1. 环境变量（最高优先级）
2. `config.yaml` 配置文件
3. 默认值

## 验证配置

### 检查环境变量是否生效
```bash
# 启动服务后，检查日志输出
# 如果看到 "从环境变量 {VAR} 读取API密钥" 的调试日志，表示环境变量生效
```

### 测试 API 连接
```bash
# 测试 DeepSeek 模型
curl -X POST http://localhost:11435/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

## 安全注意事项

### ✅ 应该做
- 将 `.env` 添加到 `.gitignore`（已配置）
- 定期更新 API 密钥
- 使用不同的密钥用于开发和生产环境
- 在 `.env.example` 中保留占位符，作为模板

### ❌ 禁止做
- 不要将 `.env` 文件提交到版本控制
- 不要在 `config.yaml` 中硬编码真实 API 密钥
- 不要将包含真实密钥的分支推送到远程仓库

## 分支管理

### 推送注意事项
`personal-dev` 分支包含环境变量支持代码，但不包含您的真实 API 密钥。如果您希望与他人共享这些改进：

```bash
# 确保 .env 文件没有被暂存
git status

# 只提交代码修改，不提交 .env
git add config_loader.py .gitignore .env.example PERSONAL_DEVELOPMENT.md
git commit -m "feat: 添加环境变量支持用于个人开发"
```

### 合并到 main
如果您希望将环境变量支持合并到主分支：

```bash
# 切换到 main 分支
git checkout main

# 合并 personal-dev 分支（不包含 .env 文件）
git merge personal-dev --no-ff
```

## 故障排除

### 环境变量未生效
1. 检查 `.env` 文件是否存在且格式正确
2. 确认环境变量名称与模型组匹配
3. 查看日志输出：`tail -f logs/*.log`

### 服务启动失败
1. 检查 `config.yaml` 语法：`python -c "import yaml; yaml.safe_load(open('config.yaml'))"`
2. 确认端口未被占用：`netstat -an | grep 11435`
3. 查看详细日志：在 `config.yaml` 中设置 `log_level: "DEBUG"`

## 扩展其他模型提供商

如需添加新的模型提供商支持：

1. 在 `config.yaml` 中添加模型组配置
2. 在 `.env.example` 中添加对应的环境变量
3. 系统会自动使用 `{MODEL_GROUP_UPPERCASE}_API_KEY` 环境变量

例如，添加 OpenAI 支持：
```yaml
# config.yaml
openai:
  # ... 配置
```

```env
# .env
OPENAI_API_KEY=sk-your-openai-api-key
```

## 联系与支持

如有问题，请参考项目主 README 或提交 Issue。

---
**重要提醒**：请妥善保管您的 API 密钥，避免泄露造成经济损失。