@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo Smart Ollama Proxy - 多模型路由代理
echo ========================================
echo.

REM 设置项目目录
set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo [1/4] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到Python，请先安装Python 3.7+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✅ Python版本: !PYTHON_VERSION!

echo.
echo [2/4] 检查依赖包...
python -c "import fastapi, httpx, pydantic, uvicorn, yaml" >nul 2>&1
if errorlevel 1 (
    echo ⚠️ 缺少依赖包，正在安装...
    echo 安装依赖: fastapi httpx pydantic uvicorn pyyaml
    python -m pip install --upgrade pip
    if errorlevel 1 (
        echo ❌ pip升级失败
        pause
        exit /b 1
    )
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ❌ 依赖安装失败，请手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo ✅ 依赖安装完成
) else (
    echo ✅ 依赖包已安装
)

echo.
echo [3/4] 检查配置文件...
if not exist "config.yaml" (
    echo ⚠️ 配置文件 config.yaml 不存在
    echo 正在创建示例配置文件...
    
    echo # Smart Ollama Proxy 配置 > config.yaml
    echo # 模型配置格式：每个模型包含支持的后端模式 >> config.yaml
    echo. >> config.yaml
    echo # 代理服务配置 >> config.yaml
    echo proxy: >> config.yaml
    echo   port: 11435 >> config.yaml
    echo   host: "0.0.0.0" >> config.yaml
    echo   log_level: "INFO" >> config.yaml
    echo. >> config.yaml
    echo # 本地 Ollama 配置（用于本地模型） >> config.yaml
    echo local_ollama: >> config.yaml
    echo   base_url: "http://localhost:11434" >> config.yaml
    echo   timeout: 60 >> config.yaml
    echo. >> config.yaml
    echo # 模型配置 >> config.yaml
    echo models: >> config.yaml
    echo   # DeepSeek 模型组 >> config.yaml
    echo   deepseek: >> config.yaml
    echo     description: "DeepSeek V3.2 系列模型" >> config.yaml
    echo     available_models: ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"] >> config.yaml
    echo. >> config.yaml
    echo     # OpenAI兼容后端配置 >> config.yaml
    echo     openai_backend: >> config.yaml
    echo       base_url: "https://api.deepseek.com/v1" >> config.yaml
    echo       api_key: "请在此处填写您的DeepSeek API密钥" >> config.yaml
    echo       timeout: 30 >> config.yaml
    echo       # 模型映射：虚拟模型名 -> 实际API模型名 >> config.yaml
    echo       model_mapping: >> config.yaml
    echo         "deepseek-chat": "deepseek-chat" >> config.yaml
    echo         "deepseek-reasoner": "deepseek-reasoner" >> config.yaml
    echo         "deepseek-coder": "deepseek-coder" >> config.yaml
    echo. >> config.yaml
    echo   # 本地模型组（从本地Ollama获取） >> config.yaml
    echo   local: >> config.yaml
    echo     description: "本地 Ollama 模型" >> config.yaml
    echo     available_models: []  # 自动从本地Ollama获取 >> config.yaml
    echo. >> config.yaml
    echo # 路由配置 >> config.yaml
    echo routing: >> config.yaml
    echo   # 默认后端模式（当请求没有指定时使用） >> config.yaml
    echo   default_backend_mode: "openai_backend" >> config.yaml
    echo. >> config.yaml
    echo   # 是否启用自动模型发现 >> config.yaml
    echo   auto_discover_local_models: true >> config.yaml
    echo. >> config.yaml
    echo   # 模型缓存配置 >> config.yaml
    echo   cache: >> config.yaml
    echo     enabled: true >> config.yaml
    echo     update_interval: 60  # 秒 >> config.yaml
    
    echo ✅ 已创建示例配置文件 config.yaml
    echo ⚠️ 请编辑 config.yaml 文件，填写您的API密钥
    pause
) else (
    echo ✅ 配置文件已存在
)

echo.
echo [4/4] 启动代理服务...
echo ========================================
echo 🤖 智能 Ollama 多模型路由代理
echo 📡 服务地址: http://localhost:11435
echo 🔧 配置文件: config.yaml
echo 💡 请在 Copilot 中配置 Ollama 地址为上述代理地址
echo ========================================
echo.
echo 按 Ctrl+C 停止服务
echo.

REM 直接启动服务
echo 正在启动服务...
python main.py

if errorlevel 1 (
    echo.
    echo ❌ 服务启动失败
    echo 可能的原因：
    echo 1. 端口 11435 已被占用
    echo 2. 配置文件格式错误
    echo 3. Python依赖包问题
    echo 4. 缺少必要的Python模块
    echo.
    echo 请检查以上问题后重试
    pause
    exit /b 1
)

echo.
echo 服务已正常退出
endlocal
pause