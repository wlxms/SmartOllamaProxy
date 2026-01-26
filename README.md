# 🤖 Smart Ollama Proxy - 智能多模型路由代理

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 📑 目录

- [项目概述](#项目概述)
- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [Docker 使用](#docker-使用)
- [配置说明](#配置说明)
- [API 接口](#api-接口)
- [扩展性](#扩展性)
- [常见问题](#常见问题)
- [项目文件结构](#项目文件结构)
- [支持的模型提供商](#支持的模型提供商)
- [许可证](#许可证)
- [贡献指南](#贡献指南)
- [致谢](#致谢)

## 🎯 项目概述

Smart Ollama Proxy 是一个智能路由代理，为 GitHub Copilot 和其他 AI 客户端提供统一的模型访问接口。它能够将 Ollama API 请求智能路由到不同的 AI 模型后端，包括本地 Ollama 模型和多种云端 AI API（DeepSeek、OpenAI、Claude、Groq 等）。

通过这个代理，您可以使用 GitHub Copilot、Cursor 或其他支持 Ollama 协议的客户端无缝访问数十种不同的 AI 模型，而无需修改客户端配置。

## ✨ 核心特性

- **🔌 多模型支持**: 本地 Ollama 模型 + 云端 API（DeepSeek、OpenAI、Claude、Groq 等）
- **⚙️ 智能路由**: 根据模型名称自动路由到合适的后端
- **🔧 灵活配置**: YAML 配置，模型分组管理
- **🎯 完全兼容**: 原生支持 Ollama REST API 和 OpenAI 兼容 API
- **🚀 生产就绪**: 异步 FastAPI 框架，优雅的错误处理，Windows/Linux/macOS 支持
 - **🤖 GitHub Copilot 集成**: 无缝集成，支持所有模型
 - **🔧 LiteLLM 集成**: 可选集成 LiteLLM SDK，获得重试、回退、成本跟踪等高级功能

## 🚀 快速开始

### 系统要求
- **Python**: 3.7 或更高版本
- **操作系统**: Windows / Linux / macOS
- **网络**: 可访问互联网（用于云端 API）

### 1. 克隆或下载项目
```bash
git clone <repository-url>
cd smart_ollama_proxy
```

### 2. 安装依赖

#### 方式一：使用 pip（推荐）
```bash
pip install -r requirements.txt
```

#### 方式二：手动安装
```bash
pip install fastapi uvicorn httpx pydantic pyyaml
```

### 3. 配置 API 密钥

编辑 `config.yaml` 文件，将各后端的 `api_key` 替换为实际的 API 密钥：

```yaml
models:
  deepseek:
    openai_backend:
      api_key: "sk-your-deepseek-api-key-here"
  
  openai:
    openai_backend:
      api_key: "sk-your-openai-api-key-here"
  
  claude:
    openai_backend:
      api_key: "sk-your-claude-api-key-here"
  
  groq:
    openai_backend:
      api_key: "sk-your-groq-api-key-here"
```

> **注意**: 如果您只使用本地 Ollama 模型，可以跳过 API 密钥配置。

### 4. 启动代理服务

**Windows 用户:**
```bash
run.bat
```

**其他系统:**
```bash
python main.py
# 或生产环境使用
uvicorn main:app --host 0.0.0.0 --port 11435 --reload
```

### 5. 配置 GitHub Copilot

1. 打开 GitHub Copilot 设置
2. 进入 "Advanced" 或 "代理设置"
3. 将 Ollama 地址设置为 `http://localhost:11435`
4. 保存设置并重新启动 Copilot

### 6. 验证安装

访问以下地址验证服务是否正常运行：
- 服务主页: http://localhost:11435
- 模型列表: http://localhost:11435/api/tags
- API 文档: http://localhost:11435/docs

## 🐳 Docker 使用

项目提供官方 Docker 镜像，方便在容器环境中快速部署。

```bash
# 拉取最新镜像（请根据实际镜像仓库地址替换）
docker pull ghcr.io/yourorg/smart-ollama-proxy:latest

# 运行容器
docker run -d \
  -p 11435:11435 \
  -v $(pwd)/config.yaml:/app/config.yaml \
  ghcr.io/yourorg/smart-ollama-proxy:latest
```

### 环境变量（可选）

| 变量名 | 说明 |
|---|---|
| `PROXY_HOST` | 代理绑定的主机地址，默认 `0.0.0.0` |
| `PROXY_PORT` | 代理监听端口，默认 `11435` |
| `LOG_LEVEL` | 日志级别，`DEBUG`/`INFO`/`WARNING`/`ERROR`，默认 `INFO` |

容器启动时可通过 `-e` 参数传入，例如：

```bash
docker run -d -p 11435:11435 \
  -e LOG_LEVEL=DEBUG \
  -v $(pwd)/config.yaml:/app/config.yaml \
  ghcr.io/yourorg/smart-ollama-proxy:latest
```

如需自定义更多配置，请参考后面的 **配置说明** 部分。

## ⚙️ 配置说明

Smart Ollama Proxy 使用 YAML 格式的配置文件（`config.yaml`），以下是关键配置项：

### 基础配置
```yaml
proxy:
  port: 11435              # 代理服务端口
  host: "0.0.0.0"          # 绑定地址
  log_level: "INFO"        # 日志级别
  # 是否启用详细的JSON日志记录（会打印完整的请求/响应JSON数据）
  verbose_json_logging: false
  # 是否启用工具压缩优化（检测重复工具列表并压缩）
  tool_compression_enabled: true
  # 是否启用重复提示词压缩优化（从内容头开始比对与上次内容，将重复部分替换为标记）
  prompt_compression_enabled: true
  # 是否启用HTTP传输压缩（gzip/deflate）
  http_compression_enabled: true

local_ollama:
  base_url: "http://localhost:11434"  # 本地 Ollama 服务地址
```

### HTTP压缩配置
Smart Ollama Proxy 支持 HTTP 传输压缩，可以显著减少网络传输数据量，提高国际 API 调用的速度。

**全局配置**：通过 `proxy.http_compression_enabled` 控制是否启用 HTTP 压缩（默认启用）。启用后，代理会在 HTTP 请求中添加 `Accept-Encoding: gzip, deflate, br` 头，并自动处理服务器的压缩响应。

**后端级配置**：每个后端可以单独配置 `compression_enabled` 选项（默认继承全局设置）：
```yaml
models:
  deepseek:
    openai_backend:
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      timeout: 30
      compression_enabled: true  # 是否启用HTTP压缩（默认true，继承全局proxy.http_compression_enabled）
```

**注意事项**：
- 大多数 AI API（OpenAI、DeepSeek、Anthropic、Groq 等）都支持 gzip 压缩
- 本地 Ollama 服务通常不支持压缩，但启用压缩不会导致错误
- 压缩可以显著减少响应体积，特别是在长文本生成场景下
- 监控日志中会显示客户端压缩启用状态（DEBUG 级别）

### API 密钥配置
```yaml
models:
  deepseek:
    openai_backend:
      api_key: "sk-your-deepseek-api-key"
  
  openai:
    openai_backend:
      api_key: "sk-your-openai-api-key"
  
   # 其他模型组类似配置
```

### LiteLLM 配置（可选）
Smart Ollama Proxy 支持可选集成 [LiteLLM](https://github.com/BerriAI/litellm) SDK，提供更高级的功能如自动重试、回退、成本跟踪等。要启用 LiteLLM：

1. 安装 LiteLLM：`pip install litellm`
2. 在配置中添加 LiteLLM 参数：

```yaml
models:
  deepseek:
    openai_backend:
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      use_litellm: true  # 启用 LiteLLM（默认 true，如果已安装）
      litellm_params:    # LiteLLM 专用参数
        max_retries: 3   # 最大重试次数
        cache: true      # 启用缓存
        timeout: 30      # 超时时间
```

**注意**：如果未安装 `litellm` 包，系统会自动回退到标准的 HTTP 请求，不影响正常使用。

### LiteLLM 专用后端配置
从 v1.1 开始，Smart Ollama Proxy 支持独立的 `litellm_backend` 配置，专门用于 LiteLLM 集成：

```yaml
models:
  deepseek:
    # OpenAI兼容后端（使用OpenAI SDK + HTTP回退）
    openai_backend:
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      # backend_type: "openai_sdk"  # 可选：openai_sdk, http, openai (默认自动检测)
    
    # LiteLLM专用后端
    litellm_backend:
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      max_retries: 3   # LiteLLM专用参数
      cache: true      # 启用缓存
      timeout: 30      # 超时时间
```

**两种配置方式的区别**：
1. **`openai_backend` + `use_litellm: true`**：兼容模式，优先使用 OpenAI SDK，失败回退 HTTP
2. **`litellm_backend`**：专用模式，直接使用 LiteLLM SDK 处理所有请求

### 后端路由器架构
Smart Ollama Proxy 使用模块化的后端路由器架构：

| 后端类型 | 路由器类 | 说明 |
|---------|----------|------|
| `openai_backend` | `OpenAIBackendRouter` | 优先使用 OpenAI Python SDK，失败时回退到 HTTP 请求 |
| `litellm_backend` | `LiteLLMRouter` | 专门使用 LiteLLM SDK 处理请求 |
| `openai_sdk` | `OpenAISDKBackendRouter` | 仅使用 OpenAI SDK（需要显式配置 `backend_type`） |
| `ollama` | `OllamaBackendRouter` | 本地 Ollama 服务 |
| `mock` | `MockBackendRouter` | 模拟后端，用于测试 |

**自动类型推断**：系统会根据配置的 `backend_mode`（如 `openai_backend`、`litellm_backend`）自动选择合适的路由器类型。

完整的配置示例请参考 `config.yaml` 文件。

## 📡 API 接口

Smart Ollama Proxy 提供两种主要的 API 接口：

### 🔌 Ollama 兼容 API
完全兼容 Ollama 原生 API，支持所有标准端点：

```bash
# 获取模型列表
curl http://localhost:11435/api/tags

# 文本生成
curl -X POST http://localhost:11435/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "prompt": "解释一下Python的生成器",
    "stream": false
  }'
```

### 🎯 OpenAI 兼容 API
提供 OpenAI 兼容的聊天完成接口：

```bash
# 聊天完成
curl -X POST http://localhost:11435/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "system", "content": "你是一个编程助手"},
      {"role": "user", "content": "解释JavaScript闭包的概念"}
    ],
    "stream": true
  }'
```

### 模型命名约定

Smart Ollama Proxy 支持两种模型命名格式：

1. **纯模型名**：`deepseek-chat`、`deepseek-reasoner`、`qwen3-max`
2. **带组名的模型名**：`deepseek/deepseek-chat`、`deepseek/deepseek-reasoner`、`qwen/qwen3-max`

两种格式完全兼容，系统会自动处理。带组名的格式有助于明确指定模型组，避免歧义。

### 常用模型示例

| 模型 | 类型 | API 端点 | 用途 |
|------|------|----------|------|
| `deepseek-chat` 或 `deepseek/deepseek-chat` | 聊天模型 | `/api/chat` 或 `/v1/chat/completions` | 通用对话、代码生成 |
| `deepseek-reasoner` 或 `deepseek/deepseek-reasoner` | 推理模型 | `/api/generate` | 复杂问题推理 |
| `gpt-4o` | 智能模型 | `/v1/chat/completions` | 高质量回答、编程辅助 |
| `claude-3-5-sonnet` | 智能模型 | `/v1/chat/completions` | 创意写作、分析 |
| `llama3.2:latest` | 本地模型 | `/api/generate` | 本地推理、测试 |
| `llama-3.3-70b` | 高速推理 | `/v1/chat/completions` | 快速响应、对话 |

## 🔧 扩展性

Smart Ollama Proxy 采用模块化设计，易于扩展新的模型提供商。

### 🏗️ 系统架构

```
用户请求 → FastAPI 应用 → 模型路由器 → 后端路由器 → 实际 API 调用
```

- **模块化设计**: 通过插件化方式添加新模型提供商
- **标准接口**: 统一的后端路由器接口
- **配置驱动**: 通过配置文件轻松添加新模型

当前支持的后端类型：
- **openai_backend**: OpenAI 兼容 API（DeepSeek、OpenAI、Claude、Groq 等）
- **ollama**: 本地 Ollama 服务
- **mock**: 模拟后端（用于测试）

### 🔄 后端优先级与回退机制

Smart Ollama Proxy 支持后端优先级配置和自动回退机制。当模型组配置多个后端时，系统会按照配置文件中的顺序决定优先级，如果前一个后端失败会自动尝试下一个。

#### 配置示例

```yaml
models:
  deepseek:
    description: "DeepSeek V3.2 系列模型"
    available_models:
      deepseek-chat:
        context_length: 128000
        capabilities: ["completion", "tools"]
        actual_model: "deepseek-chat"
    
    # 后端配置（按配置顺序决定优先级，如果前一个失败则尝试后一个）
    # OpenAI兼容后端配置（优先级1）
    openai_backend:
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      timeout: 30
    
    # LiteLLM兼容后端配置（优先级2）
    litellm_backend:
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      timeout: 30
      max_retries: 3
      cache: true
```

#### 工作原理

1. **优先级顺序**：YAML 配置文件中后端配置的书写顺序决定优先级
2. **自动回退**：当请求失败（网络错误、认证失败、API限流等）时自动尝试下一个后端
3. **路由器复用**：相同配置的后端共享路由器实例，避免重复创建
4. **兼容性**：现有 API 完全兼容，可通过 `backend_mode` 参数指定特定后端

#### 日志输出示例

当启用调试日志时，系统会显示回退过程：

```
尝试后端 1/2: deepseek.openai_backend
尝试后端 2/2: deepseek.litellm_backend
✅ 后端 deepseek.litellm_backend 请求成功
```

#### 使用建议

- **高可用配置**：为关键模型配置多个后端，提高系统可用性
- **优先级规划**：将性能更好、成本更低的后端配置在前
- **测试验证**：使用 `test_priority_fallback.py` 测试优先级和回退逻辑

### 📁 项目文件结构

```
smart_ollama_proxy/
├── 🧪 test_api.py              # API 测试脚本
├── 🧪 test_mock.py             # 模拟后端测试
├── 🧪 test_refactor.py         # 重构测试脚本
├── 🧪 test_priority_fallback.py # 后端优先级和回退测试
└── 🧪 test_litellm_integration.py # LiteLLM集成测试
```

## ❗ 常见问题

### 1. 配置加载失败
- **检查 YAML 语法**: `python -c "import yaml; yaml.safe_load(open('config.yaml'))"`
- **检查缩进格式**: YAML 对缩进要求严格
- **验证文件编码**: 使用 UTF-8 编码

### 2. API 请求失败
- **检查 API 密钥**: 确保配置正确
- **检查网络连接**: 确保可以访问对应的 API 服务
- **查看详细日志**: 在配置文件中设置 `log_level: "DEBUG"`

### 3. 模型未找到
- **检查模型列表**: `curl http://localhost:11435/api/tags`
- **验证模型配置**: 检查 `config.yaml` 中的模型配置

### 4. 本地 Ollama 连接失败
- **检查 Ollama 服务**: 运行 `curl http://localhost:11434/api/tags`
- **验证配置**: 检查 `local_ollama.base_url` 配置
- **安装 Ollama**: 可从 https://ollama.com/ 下载安装

### 5. GitHub Copilot 连接问题
- **检查代理服务**: `curl http://localhost:11435/`
- **验证配置**: 确保 Copilot 设置中的 Ollama 地址为 `http://localhost:11435`
- **检查防火墙**: 确保端口 11435 未被阻止

### 调试建议
- **启用调试日志**: 在配置文件中设置 `log_level: "DEBUG"`
- **检查服务状态**: `curl http://localhost:11435/health`
- **验证模型列表**: `curl http://localhost:11435/api/tags`

## 📁 项目文件结构

```
smart_ollama_proxy/
├── main.py                    # 主应用入口，FastAPI 应用
├── config.yaml               # 主配置文件
├── config_loader.py          # 配置加载、模型路由
├── backend_router.py         # 后端路由器系统
├── requirements.txt          # Python 依赖
├── README.md                 # 本文档
├── run.bat                   # Windows 启动脚本
├── test_api.py              # API 测试脚本
├── test_mock.py             # 模拟后端测试
├── test_refactor.py         # 重构测试脚本
├── test_priority_fallback.py # 后端优先级和回退测试
└── test_litellm_integration.py # LiteLLM集成测试
```

## 📊 支持的模型提供商

- **DeepSeek**: deepseek-chat, deepseek-reasoner（支持 thinking 能力）
- **OpenAI**: gpt-4o, gpt-4o-mini, gpt-3.5-turbo
- **Anthropic**: claude-3-5-sonnet, claude-3-opus
- **Groq**: llama-3.3-70b, mixtral-8x7b（高速推理）
- **本地 Ollama**: 支持所有 Ollama 模型

## 📜 许可证

MIT License

```
Copyright (c) 2026 Smart Ollama Proxy Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 🤝 贡献指南

欢迎通过以下方式为项目做贡献：
- 报告 bug 和问题
- 提交功能请求
- 提交代码改进和修复
- 改进文档

### 开发规范
- 遵循 PEP 8 编码规范
- 使用类型注解
- 为新功能添加测试
- 更新相关文档

感谢所有为项目做出贡献的人！

## 🙏 致谢

感谢以下项目和工具的支持：
- [FastAPI](https://fastapi.tiangolo.com/) - 现代、快速的 Web 框架
- [Ollama](https://ollama.com/) - 本地 AI 模型运行平台
- [OpenAI API](https://platform.openai.com/) - 云端 AI 模型服务
- [DeepSeek](https://platform.deepseek.com/) - 优质的 AI 模型提供商
- [GitHub Copilot](https://github.com/features/copilot) - AI 编程助手