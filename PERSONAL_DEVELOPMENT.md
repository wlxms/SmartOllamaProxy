# 个人开发分支使用指南

本文档介绍如何在 `personal-dev` 分支上使用您个人的 API 密钥进行开发，同时保持 `config.yaml` 文件的机密信息安全。

## 分支状态

当前您位于 `personal-dev` 分支，该分支基于 `main` 分支创建，并进行了以下增强：

1. **本地配置文件支持**：API 密钥可以从本地配置文件加载，优先于主配置文件
2. **环境变量支持**：API 密钥也可以从环境变量加载，优先级最高
3. **`.env` 文件支持**：自动加载 `.env` 文件中的环境变量（可选）
4. **安全配置**：`.gitignore` 已更新，忽略敏感文件（`.env`、`*.local.yaml`、`config.personal.yaml`等）

## 快速开始

Smart Ollama Proxy 支持两种方式来管理个人 API 密钥：

1. **本地配置文件**（推荐）：创建 `config.local.yaml` 文件，包含您的真实 API 密钥
2. **环境变量**：使用 `.env` 文件或系统环境变量

### 方法一：使用本地配置文件（推荐）

本地配置文件方式更简单，不会污染系统环境变量。

#### 1. 创建本地配置文件

复制 `config.yaml` 并重命名为 `config.local.yaml`：

```bash
# 复制配置文件（不要在版本控制中提交 config.local.yaml）
cp config.yaml config.local.yaml
```

#### 2. 编辑 config.local.yaml 文件

用您自己的 API 密钥替换 `config.local.yaml` 文件中的占位符（`sk-***`）：

```yaml
# 在 config.local.yaml 中，只需修改需要覆盖的配置部分
models:
  deepseek:
    litellm_backend:
      api_key: "sk-your-real-deepseek-api-key-here"
    openai_backend:
      api_key: "sk-your-real-deepseek-api-key-here"
  
  siliconflow:
    openai_backend:
      api_key: "sk-your-real-siliconflow-api-key-here"
  
  qwen:
    openai_backend:
      api_key: "sk-your-real-qwen-api-key-here"
  
  qwen-coder:
    openai_backend:
      api_key: "sk-your-real-qwen-coder-api-key-here"
```

**注意**：只需修改需要覆盖的配置部分，其他配置会自动从主 `config.yaml` 继承。

#### 3. 启动代理服务

```bash
python main.py
```

或使用 uvicorn：

```bash
uvicorn main:app --host 0.0.0.0 --port 11435 --reload
```

### 方法二：使用环境变量（可选）

如果您偏好使用环境变量，可以继续使用 `.env` 文件。

#### 1. 复制环境变量模板

```bash
# 复制模板文件（不要在版本控制中提交 .env）
cp .env.example .env
```

#### 2. 编辑 .env 文件

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

#### 3. 启动代理服务（自动加载 .env）

```bash
python main.py
```

## 配置优先级工作原理

Smart Ollama Proxy 使用多层配置系统，优先级从高到低如下：

### 1. 环境变量（最高优先级）
- 应用启动时会自动加载 `.env` 文件（如果存在）
- 环境变量名称根据模型组自动生成：
  - `deepseek` → `DEEPSEEK_API_KEY`
  - `siliconflow` → `SILICONFLOW_API_KEY`
  - `qwen` → `QWEN_API_KEY`
  - `qwen-coder` → `QWEN_CODER_API_KEY`
- 如果设置了环境变量，它将覆盖所有文件配置

### 2. 本地配置文件（推荐使用）
- 支持的文件名（按检查顺序）：
  - `config.local.yaml`（推荐）
  - `config.personal.yaml`
  - 任何 `*.local.yaml` 文件
- 本地配置文件与主 `config.yaml` 深度合并，可以只覆盖需要修改的部分
- 文件路径相对于项目根目录

### 3. 主配置文件 (`config.yaml`)
- 包含默认配置和占位符
- 应该提交到版本控制，不包含真实 API 密钥
- 提供完整的配置结构和文档

### 4. 默认值
- 代码中定义的默认值

### 配置合并示例
假设 `config.yaml` 中有：
```yaml
models:
  deepseek:
    litellm_backend:
      api_key: "sk-***"
      timeout: 30
```

`config.local.yaml` 中有：
```yaml
models:
  deepseek:
    litellm_backend:
      api_key: "sk-your-real-key"
```

环境变量中有：
```
DEEPSEEK_API_KEY=sk-from-env
```

最终生效的配置将是：
- `api_key`: `sk-from-env`（来自环境变量，优先级最高）
- `timeout`: `30`（来自 `config.yaml`，因为本地配置文件中未覆盖）

## 验证配置

### 检查本地配置文件是否生效
```bash
# 启动服务后，检查日志输出
# 如果看到 "检测到本地配置文件: config.local.yaml" 和 "本地配置文件已合并到主配置" 的日志，表示本地配置文件生效
# 如果看到 "从环境变量 {VAR} 读取API密钥" 的日志，表示环境变量正在覆盖本地配置
```

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
- 将 `.env` 和本地配置文件添加到 `.gitignore`（已配置：`.env`、`*.local.yaml`、`config.personal.yaml`）
- 定期更新 API 密钥
- 使用不同的密钥用于开发和生产环境
- 在 `config.yaml` 中使用占位符（`sk-***`），在本地配置文件中使用真实密钥
- 在 `.env.example` 中保留占位符，作为模板（如果使用环境变量）

### ❌ 禁止做
- 不要将 `.env` 或本地配置文件（`config.local.yaml` 等）提交到版本控制
- 不要在 `config.yaml` 中硬编码真实 API 密钥
- 不要将包含真实密钥的分支推送到远程仓库
- 不要在生产环境中使用包含真实密钥的配置文件而不采取适当保护措施

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