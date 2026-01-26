# smart_ollama_proxy.py
import sys
import io
import logging

# 配置 logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("smart_ollama_proxy")

# 设置标准输出编码为 UTF-8（避免文件句柄关闭问题）
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import httpx
from utils import json
import asyncio
from typing import Optional, List

app = FastAPI(title="Smart Ollama-DeepSeek Router")

# ============ 配置区 ============
DEEPSEEK_API_KEY = "sk-d55c91e9576f4868adced78f7b80e098"  # 务必替换！
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 本地真实 Ollama 服务的地址 (默认情况下就是本机的11434端口)
LOCAL_OLLAMA_BASE_URL = "http://localhost:11434"

# 代理自身监听的端口 (可以自定义，避免与真实Ollama冲突)
PROXY_PORT = 11435  # 例如，让代理运行在11435端口

# DeepSeek 虚拟模型配置
# 这里的名称就是 Copilot 中会看到的模型名称，也是路由判断的依据
VIRTUAL_DEEPSEEK_MODELS = [
    {
        "name": "deepseek-chat",
        "description": "DeepSeek Chat (via API)",
        "backend": "deepseek",  # 路由标识
        "actual_model": "deepseek-chat"  # 实际传递给DeepSeek API的模型名
    },
    {
        "name": "deepseek-coder",
        "description": "DeepSeek Coder (via API)",
        "backend": "deepseek",
        "actual_model": "deepseek-coder"
    }
]
# ===============================

# 存储真实的本地模型列表 (启动时获取，并定期更新)
local_models_cache = []

class OllamaGenerateRequest(BaseModel):
    model: str
    prompt: str
    stream: bool = False
    options: dict = {}

async def fetch_local_models():
    """从本地真实的 Ollama 服务获取模型列表"""
    global local_models_cache
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{LOCAL_OLLAMA_BASE_URL}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"从 Ollama 获取的原始数据: {data}")
                local_models_cache = data.get("models", [])
                logger.info(f"已获取本地 Ollama 模型列表，共 {len(local_models_cache)} 个模型")
            else:
                logger.warning("无法从本地 Ollama 获取模型列表")
                local_models_cache = []
    except Exception as e:
        logger.error(f"连接本地 Ollama 失败: {e}")
        local_models_cache = []

async def periodic_model_update():
    """周期性更新本地模型列表"""
    while True:
        await asyncio.sleep(60)  # 每60秒更新一次
        await fetch_local_models()

def get_virtual_model_info(model_name: str) -> Optional[dict]:
    """检查请求的模型是否为虚拟的 DeepSeek 模型"""
    for vm in VIRTUAL_DEEPSEEK_MODELS:
        if vm["name"] == model_name:
            return vm
    return None

@app.on_event("startup")
async def startup_event():
    """启动时获取一次本地模型列表，并启动定期更新任务"""
    logger.info(f"智能路由代理启动，监听端口 {PROXY_PORT}")
    logger.info(f"本地 Ollama 地址: {LOCAL_OLLAMA_BASE_URL}")
    logger.info(f"虚拟 DeepSeek 模型: {[vm['name'] for vm in VIRTUAL_DEEPSEEK_MODELS]}")
    await fetch_local_models()
    asyncio.create_task(periodic_model_update())

@app.get("/api/tags")
async def get_models():
    """合并本地模型和虚拟模型，返回给 Copilot"""
    combined_models = local_models_cache.copy()
    
    # 添加虚拟模型信息，保持与本地模型相同的结构
    for vm in VIRTUAL_DEEPSEEK_MODELS:
        # 根据真实 deepseek-v3.1 模型的数据结构构建虚拟模型
        combined_models.append({
            "name": vm["name"],
            "model": vm["name"],  # 与 name 相同
            "remote_model": vm.get("actual_model", vm["name"]),  # 实际模型名
            "remote_host": "https://api.deepseek.com",  # DeepSeek API 地址
            "modified_at": "2026-01-14T05:40:00.000000+08:00",  # 当前时间
            "size": 405,  # 与真实 cloud 模型相同的大小
            "digest": "d3749919e45f955731da7a7e76849e20f7ed310725d3b8b52822e811f55d0a90",  # 示例哈希
            "details": {
                "parent_model": "",
                "format": "api",  # 使用 api 格式表示这是 API 模型
                "family": "deepseek",
                "families": ["deepseek"],
                "parameter_size": "7B",  # 合理的参数大小
                "quantization_level": "FP8_E4M3"  # 与真实模型相同的量化级别
            }
        })
    
    result = {"models": combined_models}
    logger.info(f"返回的 /api/tags 数据: {result}")
    return result

@app.post("/api/generate")
async def generate(request: OllamaGenerateRequest):
    """智能路由生成请求"""
    
    # 1. 判断请求的是否为虚拟 DeepSeek 模型
    virtual_model = get_virtual_model_info(request.model)
    
    if virtual_model:
        # 2. 路由到 DeepSeek API
        logger.info(f"路由到 DeepSeek: {request.model}")
        return await handle_deepseek_request(request, virtual_model["actual_model"])
    else:
        # 3. 路由到本地真实的 Ollama
        logger.info(f"路由到本地 Ollama: {request.model}")
        return await handle_local_ollama_request(request)

async def handle_deepseek_request(request: OllamaGenerateRequest, actual_model: str):
    """处理 DeepSeek API 请求"""
    # 转换请求格式
    messages = [{"role": "user", "content": request.prompt}]
    
    deepseek_data = {
        "model": actual_model,
        "messages": messages,
        "stream": request.stream,
        "temperature": request.options.get("temperature", 0.7),
        "max_tokens": request.options.get("num_predict", 2048),
    }
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 处理流式响应
    if request.stream:
        async def deepseek_stream():
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", DEEPSEEK_API_URL, json=deepseek_data, headers=headers) as deepseek_response:
                    if deepseek_response.status_code != 200:
                        error_text = await deepseek_response.aread()
                        yield f"data: {json.dumps({'error': error_text.decode()})}\n\n"
                        return
                    
                    async for line in deepseek_response.aiter_lines():
                        if line.startswith("data: "):
                            sse_data = line[6:]
                            if sse_data.strip() == "[DONE]":
                                yield f"data: {json.dumps({'model': request.model, 'done': True})}\n\n"
                                break
                            try:
                                openai_chunk = json.loads(sse_data)
                                if "choices" in openai_chunk and openai_chunk["choices"]:
                                    delta = openai_chunk["choices"][0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        ollama_chunk = {
                                            "model": request.model,
                                            "response": content,
                                            "done": False
                                        }
                                        yield f"data: {json.dumps(ollama_chunk)}\n\n"
                            except json.JSONDecodeError:
                                continue
        
        return StreamingResponse(deepseek_stream(), media_type="text/event-stream")
    
    # 处理非流式响应
    else:
        async with httpx.AsyncClient(timeout=30.0) as client:
            deepseek_response = await client.post(DEEPSEEK_API_URL, json=deepseek_data, headers=headers)
            if deepseek_response.status_code != 200:
                raise HTTPException(status_code=deepseek_response.status_code, 
                                  detail=deepseek_response.text)
            
            openai_result = deepseek_response.json()
            ollama_result = {
                "model": request.model,
                "response": openai_result["choices"][0]["message"]["content"],
                "done": True,
                "total_duration": openai_result.get("usage", {}).get("total_tokens", 0) * 50_000_000,
            }
            return ollama_result

async def handle_local_ollama_request(request: OllamaGenerateRequest):
    """将请求转发给本地真实的 Ollama 服务"""
    target_url = f"{LOCAL_OLLAMA_BASE_URL}/api/generate"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 对于流式请求，直接透传
        if request.stream:
            async def local_stream():
                async with client.stream("POST", target_url, 
                                       json=request.model_dump(),
                                       timeout=60.0) as ollama_response:
                    async for chunk in ollama_response.aiter_bytes():
                        yield chunk
            
            return StreamingResponse(local_stream(), 
                                   media_type="application/x-ndjson")
        
        # 非流式请求
        else:
            ollama_response = await client.post(target_url, json=request.model_dump())
            
            if ollama_response.status_code != 200:
                raise HTTPException(status_code=ollama_response.status_code,
                                  detail=ollama_response.text)
            
            return JSONResponse(content=ollama_response.json())

async def fetch_ollama_version():
    """从本地 Ollama 服务获取版本号"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{LOCAL_OLLAMA_BASE_URL}/api/version")
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"从 Ollama 获取的版本信息: {data}")
                return data
    except Exception as e:
        logger.error(f"获取 Ollama 版本失败: {e}")
    return None

@app.get("/api/version")
async def get_version():
    """返回版本信息，优先使用真实 Ollama 的版本"""
    ollama_version = await fetch_ollama_version()
    if ollama_version:
        return ollama_version
    else:
        # 如果无法获取真实版本，返回兼容版本
        return {
            "version": "0.6.4"
        }

@app.post("/api/show")
async def show_model(request: Request):
    """
    处理 /api/show 请求，返回模型信息
    根据 Ollama API 文档：POST /api/show 需要 {"model": "模型名称"}
    """
    try:
        body = await request.json()
        model_name = body.get("model", "")
        logger.info(f"收到 /api/show 请求，模型: {model_name}")
        
        # 检查是否为虚拟模型
        virtual_model = get_virtual_model_info(model_name)
        if virtual_model:
            # 返回虚拟模型信息，基于真实 deepseek-v3.1 模型的结构
            return {
                "model": model_name,
                "details": {
                    "parent_model": "",
                    "format": "api",  # 使用 api 格式表示这是 API 模型
                    "family": "deepseek",
                    "families": ["deepseek"],
                    "parameter_size": "7B",  # 合理的参数大小
                    "quantization_level": "FP8_E4M3"  # 与真实模型相同的量化级别
                },
                "modelfile": "# Virtual DeepSeek model via API\nFROM api:deepseek\n\n# System prompt\nSYSTEM \"You are a helpful AI assistant.\"",
                "template": "{{ .Prompt }}",  # 使用与真实模型相同的模板
                "parameters": "num_ctx 4096\nnum_predict 2048\ntemperature 0.7",  # 使用字符串格式，与真实模型一致
                "license": "",
                "system": "You are a helpful AI assistant.",
                "remote_model": virtual_model.get("actual_model", model_name),
                "remote_host": "https://api.deepseek.com",
                "model_info": {
                    "general.architecture": "deepseek",
                    "general.basename": virtual_model.get("actual_model", model_name),
                    "deepseek.context_length": 163840,
                    "deepseek.embedding_length": 7168
                },
                "capabilities": ["completion", "tools", "thinking"],  # 与 deepseek-v3.1 相同的能力
                "modified_at": "2026-01-14T05:40:00.000000+08:00"
            }
        else:
            # 转发到本地 Ollama
            target_url = f"{LOCAL_OLLAMA_BASE_URL}/api/show"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(target_url, json=body)
                if response.status_code == 200:
                    response_data = response.json()
                    logger.info(f"本地 Ollama /api/show 原始返回: {response_data}")
                    return response_data
                else:
                    # 如果 Ollama 返回错误，返回一个基本响应
                    logger.warning(f"Ollama /api/show 返回 {response.status_code}, 使用模拟响应")
                    return {
                        "model": model_name,
                        "details": {
                            "parent_model": "",
                            "format": "gguf",
                            "family": "unknown",
                            "families": ["unknown"],
                            "parameter_size": "unknown",
                            "quantization_level": "unknown"
                        },
                        "modelfile": "",
                        "template": "",
                        "parameters": {},
                        "license": "",
                        "system": ""
                    }
    except Exception as e:
        logger.error(f"/api/show 处理错误: {e}")
        return {
            "model": "",
            "details": {},
            "modelfile": "",
            "template": "",
            "parameters": {},
            "license": "",
            "system": ""
        }

@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """
    处理 OpenAI 兼容的 /v1/chat/completions 端点
    根据模型名称路由到适当的后端
    """
    try:
        body = await request.json()
        model_name = body.get("model", "")
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        
        logger.info(f"收到 OpenAI 聊天完成请求，模型: {model_name}, 消息数: {len(messages)}, 流式: {stream}")
        
        # 检查是否为虚拟 DeepSeek 模型
        virtual_model = get_virtual_model_info(model_name)
        
        if virtual_model:
            # 路由到 DeepSeek API
            logger.info(f"路由到 DeepSeek API: {model_name}")
            return await handle_openai_deepseek_request(body, virtual_model["actual_model"])
        else:
            # 路由到本地 Ollama 的 OpenAI 兼容端点
            logger.info(f"路由到本地 Ollama OpenAI 端点: {model_name}")
            return await handle_openai_ollama_request(body)
            
    except Exception as e:
        logger.error(f"处理 /v1/chat/completions 错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def handle_openai_deepseek_request(body: dict, actual_model: str):
    """处理 DeepSeek API 的 OpenAI 格式请求"""
    # 准备 DeepSeek API 请求
    deepseek_data = {
        "model": actual_model,
        "messages": body.get("messages", []),
        "stream": body.get("stream", False),
        "temperature": body.get("temperature", 0.7),
        "max_tokens": body.get("max_tokens", 2048),
    }
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 处理流式响应
    if body.get("stream", False):
        async def deepseek_stream():
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", DEEPSEEK_API_URL, json=deepseek_data, headers=headers) as deepseek_response:
                    if deepseek_response.status_code != 200:
                        error_text = await deepseek_response.aread()
                        yield f"data: {json.dumps({'error': error_text.decode()})}\n\n"
                        return
                    
                    async for line in deepseek_response.aiter_lines():
                        if line.startswith("data: "):
                            yield line + "\n"
        
        return StreamingResponse(deepseek_stream(), media_type="text/event-stream")
    
    # 处理非流式响应
    else:
        async with httpx.AsyncClient(timeout=30.0) as client:
            deepseek_response = await client.post(DEEPSEEK_API_URL, json=deepseek_data, headers=headers)
            if deepseek_response.status_code != 200:
                raise HTTPException(status_code=deepseek_response.status_code,
                                  detail=deepseek_response.text)
            
            return JSONResponse(content=deepseek_response.json())

async def handle_openai_ollama_request(body: dict):
    """将 OpenAI 格式请求转发到本地 Ollama 的 /v1/chat/completions 端点"""
    target_url = f"{LOCAL_OLLAMA_BASE_URL}/v1/chat/completions"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 对于流式请求，直接透传
        if body.get("stream", False):
            async def ollama_stream():
                async with client.stream("POST", target_url,
                                       json=body,
                                       timeout=60.0) as ollama_response:
                    async for chunk in ollama_response.aiter_bytes():
                        yield chunk
            
            return StreamingResponse(ollama_stream(),
                                   media_type="text/event-stream")
        
        # 非流式请求
        else:
            ollama_response = await client.post(target_url, json=body)
            
            if ollama_response.status_code != 200:
                raise HTTPException(status_code=ollama_response.status_code,
                                  detail=ollama_response.text)
            
            return JSONResponse(content=ollama_response.json())

@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_ollama(path: str, request: Request):
    """
    将其他 Ollama API 请求转发到本地 Ollama 服务
    例如：/api/chat, /api/embeddings, /api/pull, /api/delete 等
    """
    # 排除已经特殊处理的端点
    if path in ["tags", "generate", "version", "show"]:
        # 这些端点已经有特殊处理，不应该通过此通用路由
        # 但为了兼容性，仍然允许通过（它们会有自己的处理程序）
        pass
    
    target_url = f"{LOCAL_OLLAMA_BASE_URL}/api/{path}"
    logger.info(f"转发请求 {request.method} /api/{path} -> {target_url}")
    
    # 获取请求体
    body = None
    if request.method in ["POST", "PUT"]:
        body = await request.body()
    
    # 转发请求
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                content=body,
                headers=dict(request.headers),
                params=dict(request.query_params)
            )
            
            logger.info(f"转发成功 {request.method} /api/{path} -> 状态码: {response.status_code}")
            
            # 返回响应
            return JSONResponse(
                content=response.json() if response.content else None,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except Exception as e:
            logger.error(f"转发失败 {request.method} /api/{path} -> 错误: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")

@app.get("/")
async def root():
    return {
        "message": "Smart Ollama-DeepSeek 路由代理",
        "endpoints": {
            "GET /api/tags": "获取合并后的模型列表",
            "POST /api/generate": "智能路由生成请求",
            "GET /api/version": "获取版本信息",
            "ANY /api/{path}": "转发其他 Ollama API 请求"
        },
        "config": {
            "proxy_port": PROXY_PORT,
            "local_ollama": LOCAL_OLLAMA_BASE_URL,
            "virtual_models": [vm["name"] for vm in VIRTUAL_DEEPSEEK_MODELS]
        }
    }

if __name__ == "__main__":
    import uvicorn
    logger.info("=" * 60)
    logger.info("🤖 智能 Ollama-DeepSeek 路由代理")
    logger.info("=" * 60)
    logger.info(f"📡 代理服务运行在: http://localhost:{PROXY_PORT}")
    logger.info(f"🔗 本地 Ollama: {LOCAL_OLLAMA_BASE_URL}")
    logger.info(f"✨ 虚拟模型: {[vm['name'] for vm in VIRTUAL_DEEPSEEK_MODELS]}")
    logger.info("")
    logger.info("💡 请在 Copilot 中配置 Ollama 地址为上述代理地址")
    logger.info("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=PROXY_PORT)