# 🤖 Smart Ollama Proxy - 智能多模型路由代理

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 🎯 项目概述

Smart Ollama Proxy 是一个智能路由代理，为 GitHub Copilot、Cursor 和其他 AI 客户端提供统一的模型访问接口。它能够将 Ollama API 请求智能路由到不同的 AI 模型后端，包括本地 Ollama 模型和多种云端 AI API（DeepSeek、OpenAI、Claude、Groq、硅基流动、通义千问等）。

通过这个代理，您可以使用 GitHub Copilot、Cursor 或其他支持 Ollama 协议的客户端无缝访问数十种不同的 AI 模型，而无需修改客户端配置。

## ✨ 核心特性

- **🔌 多模型支持**: 本地 Ollama 模型 + 云端 API（DeepSeek、硅基流动、通义千问、OpenAI、Claude、Groq 等）
- **⚙️ 智能路由**: 根据模型名称自动路由到合适的后端，支持后端优先级和自动回退
- **🔧 灵活配置**: YAML 配置 + 环境变量 + 本地配置文件，支持个人开发分支
- **🎯 完全兼容**: 原生支持 Ollama REST API 和 OpenAI 兼容 API
- **🚀 生产就绪**: 异步 FastAPI 框架，优雅的错误处理，Windows/Linux/macOS 支持
- **📊 智能日志系统**: 支持流程、性能、数据、进度四种日志类型，异步处理，进度条显示
- **⚡ 性能优化**: HTTP 客户端池复用、工具压缩、提示词压缩、HTTP 传输压缩
- **🔄 模块化架构**: 后端路由器工厂 + 核心组件，易于扩展新的模型提供商
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
```bash
pip install -r requirements.txt
```

### 3. 配置 API 密钥

#### 方式一：使用本地配置文件（推荐）
```bash
# 复制配置文件模板
cp config.yaml config.local.yaml
# 编辑 config.local.yaml，替换 API 密钥占位符
```

#### 方式二：使用环境变量
```bash
# 复制环境变量模板
cp .env.example .env
# 编辑 .env 文件，设置 API 密钥
```

详细配置说明请参考 [PERSONAL_DEVELOPMENT.md](PERSONAL_DEVELOPMENT.md)。

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

## ⚙️ 配置说明

Smart Ollama Proxy 支持多层配置系统，优先级从高到低：

1. **环境变量**（最高优先级）
2. **本地配置文件** (`config.local.yaml`)
3. **主配置文件** (`config.yaml`)

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

### 环境变量配置
支持通过环境变量设置 API 密钥，环境变量名格式：`{模型组大写}_API_KEY`
- DeepSeek: `DEEPSEEK_API_KEY`
- 硅基流动: `SILICONFLOW_API_KEY`
- 通义千问: `QWEN_API_KEY`
- 通义千问Coder: `QWEN_CODER_API_KEY`

### 模型配置示例
```yaml
models:
  deepseek:
    description: "DeepSeek V3.2 系列模型"
    available_models:
      deepseek-chat:
        context_length: 128000
        embedding_length: 6400
        capabilities: ["completion", "tools"]
        actual_model: "deepseek-chat"
      deepseek-reasoner:
        context_length: 128000
        embedding_length: 6400
        capabilities: ["completion", "tools", "thinking"]
        actual_model: "deepseek-reasoner"
    
    # 后端配置（按配置顺序决定优先级，如果前一个失败则尝试后一个）
    litellm_backend:  # 优先级1
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      timeout: 30
      max_retries: 3
      cache: true
    
    openai_backend:   # 优先级2
      base_url: "https://api.deepseek.com/v1"
      api_key: "sk-your-deepseek-api-key"
      timeout: 30
```

## 📊 智能日志系统

Smart Ollama Proxy 采用统一的智能日志系统，支持四种日志类型：

### 日志类型
| 类型 | 用途 | 默认行为 |
|------|------|----------|
| **流程日志** (process) | 常规操作日志，记录程序运行状态 | 保存到文件，控制台显示，异步处理 |
| **性能日志** (performance) | 性能监控，耗时统计，性能指标 | 保存到文件，控制台不显示，同步处理（需要即时性） |
| **数据日志** (data) | 请求/响应数据统计 | 不保存到文件，控制台显示数据摘要，异步处理 |
| **进度日志** (progress) | 循环滚动进度条显示 | 不保存到文件，控制台显示，同步处理（需要即时性） |

### 配置示例
```yaml
logging:
  enabled: true
  log_dir: "logs"
  log_level: "INFO"
  
  # 日志类型配置
  log_types:
    process:
      enabled: true
      save_to_file: true
      show_in_console: true
      async_mode: true
    performance:
      enabled: true
      save_to_file: true
      show_in_console: false
      async_mode: false
    data:
      enabled: true
      save_to_file: false
      show_in_console: false
      async_mode: true
    progress:
      enabled: true
      save_to_file: false
      show_in_console: true
      async_mode: false
```

### 进度条显示
系统支持在长时间操作时显示进度条，如：
```
处理中: [||||||||||          ] 50% (5.2s)
```

## 🏗️ 系统架构

### 架构图
```
用户请求
    ↓
FastAPI 应用 (main.py)
    ↓
模型路由器 (config_loader.py)
    ↓
后端路由器工厂 (backend_router_factory.py)
    ↓
[openai_router | litellm_router | ollama_router | mock_router]
    ↓
核心组件 [cache_manager | client_manager | response_converter]
    ↓
HTTP客户端池 (client_pool.py)
    ↓
实际 API 调用
```

### 核心组件
- **cache_manager.py**: 工具缓存和提示词缓存管理
- **client_manager.py**: HTTP 客户端管理和健康检查
- **response_converter.py**: 响应格式转换（Ollama ↔ OpenAI）
- **client_pool.py**: HTTP 客户端池，复用相同配置的客户端

## 🔄 后端路由器架构

### 路由器类型
| 路由器类 | 后端类型 | 说明 |
|----------|----------|------|
| `OpenAIBackendRouter` | `openai_backend` | OpenAI 兼容 API，优先使用 OpenAI SDK，失败回退 HTTP |
| `LiteLLMRouter` | `litellm_backend` | 专门使用 LiteLLM SDK 处理请求 |
| `OllamaBackendRouter` | `ollama` | 本地 Ollama 服务 |
| `MockBackendRouter` | `mock` | 模拟后端，用于测试 |

### 自动类型推断
系统根据配置的 `backend_mode` 自动选择合适的路由器：
- `openai_backend` → `OpenAIBackendRouter`
- `litellm_backend` → `LiteLLMRouter`
- 本地模型 → `OllamaBackendRouter`
- 测试环境 → `MockBackendRouter`

### 后端优先级与回退机制
当模型组配置多个后端时，系统按照配置文件中的顺序决定优先级：
1. 尝试第一个后端
2. 如果失败（网络错误、认证失败、API限流等），自动尝试下一个后端
3. 继续直到成功或所有后端都失败

日志输出示例：
```
尝试后端 1/2: deepseek.openai_backend
尝试后端 2/2: deepseek.litellm_backend
✅ 后端 deepseek.litellm_backend 请求成功
```

## 📡 API 接口

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

### 支持的端点
- `GET /api/tags` - 获取合并的模型列表（本地+虚拟）
- `POST /api/generate` - Ollama 格式文本生成
- `POST /v1/chat/completions` - OpenAI 格式聊天完成
- `GET /api/version` - 获取版本信息
- `POST /api/show` - 获取模型详细信息
- `ANY /api/{path}` - 转发其他 Ollama API 请求
- `GET /api/client-pool` - 查看 HTTP 客户端池状态

## ⚡ 性能优化

### HTTP 客户端池
为每个唯一的 `(base_url, api_key, http2)` 组合创建并复用单个 `httpx.AsyncClient` 实例，显著提高连接复用率，减少资源消耗。

### 工具压缩优化
检测重复的工具列表并压缩，减少请求体积：
- 相同工具列表只发送一次
- 后续请求引用工具 ID
- 显著减少包含大量工具的请求体积

### 提示词压缩优化
从内容头开始比对与上次内容，将重复部分替换为标记：
- 识别并标记重复的提示词前缀
- 减少重复传输相同内容
- 特别适合对话式应用的连续请求

### HTTP 传输压缩
启用 HTTP 请求的 `Accept-Encoding: gzip, deflate, br` 头，自动处理服务器压缩响应：
- 显著减少网络传输数据量
- 提高国际 API 调用的速度
- 支持全局和后端级配置

## 📁 项目文件结构

```
smart_ollama_proxy/
├── 🚀 核心文件
│   ├── main.py                    # FastAPI 应用入口点
│   ├── config.yaml               # 主配置文件
│   ├── config.local.example.yml   # 本地配置文件示例
│   ├── config_loader.py          # 配置加载、模型路由、环境变量支持
│   ├── client_pool.py            # HTTP 客户端池管理
│   ├── smart_logger.py           # 智能统一日志系统
│   ├── utils.py                  # 工具函数（JSON 处理、Unicode 清理）
│   ├── requirements.txt          # Python 依赖
│   ├── run.bat                   # Windows 启动脚本
│   ├── README.md                 # 本文档
│   ├── AGENTS.md                 # AI 代理开发指南
│   └── PERSONAL_DEVELOPMENT.md   # 个人开发分支使用指南
│
├── 🛠️ 路由器模块 (routers/)
│   ├── __init__.py
│   ├── base_router.py            # 后端路由器抽象基类
│   ├── backend_router_factory.py # 后端路由器工厂
│   ├── openai_router.py          # OpenAI 兼容 API 路由器
│   ├── litellm_router.py         # LiteLLM SDK 路由器
│   ├── ollama_router.py          # 本地 Ollama 路由器
│   ├── mock_router.py            # 模拟路由器（测试用）
│   └── core/                     # 核心组件
│       ├── __init__.py
│       ├── cache_manager.py      # 工具和提示词缓存管理
│       ├── client_manager.py     # HTTP 客户端管理
│       └── response_converter.py # 响应格式转换器
│
├── 🧪 测试文件 (tests/)
│   ├── test_api.py              # API 端点测试
│   ├── test_client_pool.py      # 客户端池测试
│   ├── test_litellm_integration.py # LiteLLM 集成测试
│   ├── test_litellm_serialization.py # LiteLLM 序列化测试
│   ├── test_mock.py             # 模拟后端测试
│   ├── test_new_architecture.py # 新架构测试
│   ├── test_priority_fallback.py # 后端优先级和回退测试
│   ├── test_refactor.py         # 重构测试
│   └── verify_fixes.py          # 修复验证测试
│
├── 📊 日志目录 (logs/)           # 日志文件存储目录
├── 🔧 配置文件
│   ├── .env.example             # 环境变量示例文件
│   └── .gitignore               # Git 忽略文件配置
└── 🛠️ 开发工具
    ├── test_logger_fix.py       # 日志修复测试
    ├── test_new_progressbar.py  # 新进度条测试
    └── test_progressbar.py      # 进度条测试
```

## 🔧 开发指南

### 个人开发分支
项目支持个人开发分支，允许开发者使用自己的 API 密钥而不影响主配置：
1. 创建 `config.local.yaml` 文件
2. 仅覆盖需要的配置部分
3. 配置文件被 `.gitignore` 排除，不会提交到版本控制

详细指南请参考 [PERSONAL_DEVELOPMENT.md](PERSONAL_DEVELOPMENT.md)。

### 运行测试
```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_api.py -v

# 运行单个测试函数
python -m pytest tests/test_api.py::test_api_endpoints -v

# 带覆盖率测试
python -m pytest tests/ --cov=. --cov-report=html
```

### 代码规范
- 遵循 PEP 8 编码规范
- 使用类型注解（Python 3.7+）
- 为新功能添加测试
- 更新相关文档

### 添加新的模型提供商
1. 在 `config.yaml` 中添加新的模型组配置
2. 根据需要添加新的路由器实现（可选）
3. 更新 `config_loader.py` 中的模型路由逻辑
4. 添加相应的测试用例

## 📊 支持的模型提供商

- **DeepSeek**: deepseek-chat, deepseek-reasoner（支持 thinking 能力）
- **硅基流动**: deepseek-ai/DeepSeek-V3.2
- **通义千问**: qwen3-max, qwen3-coder-flash, qwen3-coder-plus
- **OpenAI**: gpt-4o, gpt-4o-mini, gpt-3.5-turbo（需取消注释配置）
- **Anthropic**: claude-3-5-sonnet, claude-3-opus（需取消注释配置）
- **Groq**: llama-3.3-70b, mixtral-8x7b（需取消注释配置）
- **本地 Ollama**: 支持所有 Ollama 模型

## ❗ 常见问题

### 1. 配置加载失败
- **检查 YAML 语法**: `python -c "import yaml; yaml.safe_load(open('config.yaml'))"`
- **检查缩进格式**: YAML 对缩进要求严格
- **验证文件编码**: 使用 UTF-8 编码

### 2. API 请求失败
- **检查 API 密钥**: 确保配置正确或环境变量已设置
- **检查网络连接**: 确保可以访问对应的 API 服务
- **查看详细日志**: 在配置文件中设置 `log_level: "DEBUG"`

### 3. 模型未找到
- **检查模型列表**: `curl http://localhost:11435/api/tags`
- **验证模型配置**: 检查 `config.yaml` 中的模型配置
- **检查模型组名称**: 确保请求的模型属于已配置的模型组

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
- **查看客户端池状态**: `curl http://localhost:11435/api/client-pool`

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
- [httpx](https://www.python-httpx.org/) - 下一代 Python HTTP 客户端
- [Pydantic](https://docs.pydantic.dev/) - 数据验证和设置管理
- [LiteLLM](https://github.com/BerriAI/litellm) - 统一 AI API 调用库
- [DeepSeek](https://platform.deepseek.com/) - 优质的 AI 模型提供商
- [GitHub Copilot](https://github.com/features/copilot) - AI 编程助手
- [通义千问](https://tongyi.aliyun.com/) - 阿里云 AI 模型服务
- [硅基流动](https://siliconflow.cn/) - 国内 AI 模型服务平台

---
**💡 提示**: 更多技术细节和开发指南请参考 [AGENTS.md](AGENTS.md) 和 [PERSONAL_DEVELOPMENT.md](PERSONAL_DEVELOPMENT.md)。