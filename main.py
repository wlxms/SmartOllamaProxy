# smart_ollama_proxy.py - 重构版本
# 支持多模型后端配置，基于OpenAI兼容模式，使用backend路由器提高扩展性

import sys
import io
import logging
from utils import json
import asyncio
from typing import Optional, List, Dict, Any, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import httpx

from config_loader import ConfigLoader, ModelRouter, BackendConfig
from routers.backend_router_factory import BackendRouterFactory, BackendManager

# ============ 初始化 ============

# 配置 logging
import os
from datetime import datetime
from stream_logger import init_global_logger, configure_root_logging, get_global_logger

# 创建logs目录（如果不存在）
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 初始化全局日志记录器
global_logger = init_global_logger(
    log_dir=log_dir,
    max_workers=4,
    max_queue_size=1000,
    enabled=True,
    verbose_json_logging=False,
    log_level="DEBUG",
    enable_file_logging=True,
    enable_console_logging=True
)

# 配置标准logging模块，将所有日志重定向到GlobalLogger
configure_root_logging(
    level=logging.INFO,
    global_logger=global_logger
)

# 保持基本的控制台日志配置（用于早期日志记录）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("smart_ollama_proxy")
logger.info(f"全局日志记录器已初始化，日志目录: {log_dir}")

# 设置标准输出编码为 UTF-8（避免文件句柄关闭问题）
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 初始化配置和路由
config_loader = ConfigLoader("config.yaml")
model_router = ModelRouter(config_loader)

# 初始化后端管理器
backend_manager = BackendManager()

# 全局变量：是否模拟ollama连接超时（用于测试）
SIMULATE_OLLAMA_TIMEOUT = False

# 是否启用详细的JSON日志记录
VERBOSE_JSON_LOGGING = config_loader.get_verbose_json_logging()
logger.info(f"详细的JSON日志记录: {'启用' if VERBOSE_JSON_LOGGING else '禁用'}")

# 后端配置映射表（性能优化：避免每次请求都遍历）
# 键: (base_url, api_key, backend_mode) 的元组，值: router_name
_backend_config_map: Dict[tuple, str] = {}

# Ollama 可用性检查缓存（性能优化）
_ollama_available_cache = {"result": None, "timestamp": 0, "ttl": 5}

# ============ 数据模型 ============

class OllamaGenerateRequest(BaseModel):
    model: str
    prompt: str
    stream: bool = False
    options: dict = {}


# ============ 辅助函数 ============

def init_backend_routers():
    """初始化后端路由器"""
    global _backend_config_map
    _backend_config_map.clear()
    
    # 获取压缩优化配置
    tool_compression_enabled = config_loader.get_tool_compression_enabled()
    prompt_compression_enabled = config_loader.get_prompt_compression_enabled()
    
    # 获取所有后端配置
    backend_configs = config_loader.get_all_backend_configs()
    
    for backend_name, backend_config in backend_configs.items():
        try:
            # 获取压缩优化配置
            tool_compression_enabled = config_loader.get_tool_compression_enabled()
            prompt_compression_enabled = config_loader.get_prompt_compression_enabled()
            # 创建路由器
            router = BackendRouterFactory.create_router(
                backend_config,
                verbose_json_logging=VERBOSE_JSON_LOGGING,
                tool_compression_enabled=tool_compression_enabled,
                prompt_compression_enabled=prompt_compression_enabled
            )
            # 注册到管理器
            backend_manager.register_router(backend_name, router)
            
            # 构建映射表（性能优化）
            backend_mode = backend_config.backend_mode or ""
            config_key = (backend_config.base_url, backend_config.api_key, backend_mode)
            _backend_config_map[config_key] = backend_name
            
            logger.info(f"初始化后端路由器: {backend_name}")
        except Exception as e:
            logger.error(f"初始化后端路由器 {backend_name} 失败: {e}")
    
    # 初始化本地路由器（总是注册mock路由器，真实路由器在需要时创建）
    local_config = config_loader.get_local_ollama_config()
    base_url = local_config.get("base_url", "http://localhost:11434")
    
    # 总是注册mock路由器
    mock_backend_config = BackendConfig({
        "base_url": "http://mock.local",
        "timeout": 60
    })
    mock_router = BackendRouterFactory.create_router(
        mock_backend_config,
        "mock",
        verbose_json_logging=VERBOSE_JSON_LOGGING,
        tool_compression_enabled=tool_compression_enabled,
        prompt_compression_enabled=prompt_compression_enabled
    )
    backend_manager.register_router("mock", mock_router)
    logger.info("初始化模拟路由器（备用）")
    
    # 检查Ollama是否可用（仅在启动时检查，但每次API调用时会重新检查）
    ollama_available = False
    if not SIMULATE_OLLAMA_TIMEOUT:
        try:
            import socket
            # 尝试连接端口
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)  # 2秒超时
            result = sock.connect_ex(('localhost', 11434))
            sock.close()
            ollama_available = (result == 0)
        except:
            ollama_available = False
    
    if ollama_available and not SIMULATE_OLLAMA_TIMEOUT:
        # 使用真实的Ollama路由器
        local_backend_config = BackendConfig({
            "base_url": base_url,
            "timeout": local_config.get("timeout", 60)
        })
        local_router = BackendRouterFactory.create_router(
            local_backend_config,
            "ollama",
            verbose_json_logging=VERBOSE_JSON_LOGGING,
            tool_compression_enabled=tool_compression_enabled,
            prompt_compression_enabled=prompt_compression_enabled
        )
        backend_manager.register_router("local", local_router)
        logger.info("初始化本地Ollama路由器")
    else:
        # 使用模拟路由器作为本地路由器
        backend_manager.register_router("local", mock_router)
        if SIMULATE_OLLAMA_TIMEOUT:
            logger.info("模拟Ollama连接超时，使用模拟路由器作为本地路由器")
        else:
            logger.info("Ollama不可用，使用模拟路由器作为本地路由器")


async def check_ollama_available() -> bool:
    """检查Ollama是否可用（带缓存优化）"""
    import time
    
    if SIMULATE_OLLAMA_TIMEOUT:
        logger.info("模拟Ollama连接超时，返回不可用")
        return False
    
    # 检查缓存（性能优化）
    current_time = time.time()
    if (_ollama_available_cache["result"] is not None and 
        current_time - _ollama_available_cache["timestamp"] < _ollama_available_cache["ttl"]):
        return _ollama_available_cache["result"]
    
    local_config = config_loader.get_local_ollama_config()
    base_url = local_config.get("base_url", "http://localhost:11434")
    
    try:
        # 使用HTTP请求检查Ollama是否可用（使用更短的超时时间）
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            result = resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.debug(f"Ollama连接检查失败: {type(e).__name__}")
        result = False
    except Exception as e:
        logger.debug(f"Ollama连接检查异常: {type(e).__name__}")
        result = False
    
    # 更新缓存
    _ollama_available_cache["result"] = result
    _ollama_available_cache["timestamp"] = current_time
    
    return result


async def get_backend_candidates_for_model(model_name: str) -> List[Tuple[str, Optional[BackendConfig], str]]:
    """
    获取模型对应的后端路由器候选列表（按优先级排序）
    
    Returns:
        [(router_name, backend_config, actual_model), ...] 
        如果使用本地Ollama，返回[("local", None, model_name)]
    """
    # 路由请求
    backend_infos = await model_router.route_request(model_name)
    
    logger.info(f"模型 {model_name} 的路由结果: {len(backend_infos) if backend_infos else 0} 个后端配置")
    
    if backend_infos is None:
        # 使用本地Ollama
        logger.info(f"模型 {model_name} 使用本地Ollama")
        return [("local", None, model_name)]
    
    candidates = []
    for backend_config, actual_model in backend_infos:
        # 使用映射表查找路由器名称（性能优化：O(1)查找替代O(n)遍历）
        backend_mode = backend_config.backend_mode or ""
        config_key = (backend_config.base_url, backend_config.api_key, backend_mode)
        router_name = _backend_config_map.get(config_key)
        
        if router_name:
            # 检查路由器是否已注册（防止被意外删除）
            router = backend_manager.get_router(router_name)
            if router:
                logger.debug(f"复用已存在的路由器: {router_name} (base_url: {backend_config.base_url})")
                candidates.append((router_name, backend_config, actual_model))
                continue
            else:
                logger.warning(f"映射表中的路由器 {router_name} 不存在，重新创建")
                # 从映射表中移除无效条目
                _backend_config_map.pop(config_key, None)
        
        # 如果没有找到，检查是否已存在相同配置的路由器（避免重复创建）
        # 遍历已注册的路由器，查找匹配的配置
        found = False
        for existing_name, existing_router in backend_manager.routers.items():
            if hasattr(existing_router, 'config'):
                existing_config = existing_router.config
                if (existing_config.base_url == backend_config.base_url and 
                    existing_config.api_key == backend_config.api_key and
                    getattr(existing_config, 'backend_mode', None) == backend_config.backend_mode):
                    # 找到匹配的路由器，更新映射表并复用
                    logger.debug(f"找到匹配的路由器: {existing_name}，复用而不是创建新的")
                    _backend_config_map[config_key] = existing_name
                    candidates.append((existing_name, backend_config, actual_model))
                    found = True
                    break
        
        if found:
            continue
        
        # 如果确实没有找到，创建一个基于后端配置的路由器
        # 使用简化名称：基于base_url的域名
        from urllib.parse import urlparse
        
        try:
            parsed_url = urlparse(backend_config.base_url)
            domain = parsed_url.netloc.replace('.', '_')
            router_name = f"backend_{domain}"
            
            # 检查名称是否已存在，如果存在则添加后缀
            if router_name in backend_manager.routers:
                import hashlib
                # 使用配置的哈希值作为后缀，确保唯一性
                config_hash = hashlib.md5(f"{backend_config.base_url}{backend_config.api_key}".encode()).hexdigest()[:8]
                router_name = f"{router_name}_{config_hash}"
            
            # 创建并注册路由器
            logger.info(f"创建新的路由器: {router_name} (base_url: {backend_config.base_url})")
            router = BackendRouterFactory.create_router(backend_config, verbose_json_logging=VERBOSE_JSON_LOGGING)
            backend_manager.register_router(router_name, router)
            
            # 更新映射表
            _backend_config_map[config_key] = router_name
            
            candidates.append((router_name, backend_config, actual_model))
        except Exception as e:
            logger.error(f"创建路由器失败: {e}")
            # 如果解析失败，使用默认名称
            router_name = "openai_compatible"
            # 检查是否已存在
            if router_name in backend_manager.routers:
                existing_router = backend_manager.routers[router_name]
                if (hasattr(existing_router, 'config') and
                    existing_router.config.base_url == backend_config.base_url and
                    existing_router.config.api_key == backend_config.api_key and
                    getattr(existing_router.config, 'backend_mode', None) == backend_config.backend_mode):
                    _backend_config_map[config_key] = router_name
                    candidates.append((router_name, backend_config, actual_model))
                    continue
            
            router = BackendRouterFactory.create_router(backend_config, verbose_json_logging=VERBOSE_JSON_LOGGING)
            backend_manager.register_router(router_name, router)
            
            # 更新映射表
            _backend_config_map[config_key] = router_name
            
            candidates.append((router_name, backend_config, actual_model))
    
    logger.info(f"模型 {model_name} 的候选路由器: {[c[0] for c in candidates]}")
    return candidates


async def get_backend_router_for_model(model_name: str) -> Optional[Tuple[str, Optional[BackendConfig], str]]:
    """
    获取模型对应的后端路由器（兼容旧版本，返回第一个候选）
    
    Returns:
        (router_name, backend_config, actual_model) 或 None
    """
    candidates = await get_backend_candidates_for_model(model_name)
    if not candidates:
        return None
    return candidates[0]


async def try_backend_request(
    model_name: str,
    request_data: Dict[str, Any],
    stream: bool,
    convert_to_ollama: bool = False,
    support_thinking: bool = False,
    endpoint: str = "generate"
) -> Any:
    """
    尝试使用候选后端列表处理请求，失败时自动回退
    
    Args:
        model_name: 模型名称
        request_data: 请求数据
        stream: 是否流式
        convert_to_ollama: 是否转换为Ollama格式
        support_thinking: 是否支持thinking能力
        endpoint: 端点类型 ('generate' 或 'chat')
    
    Returns:
        响应数据
        
    Raises:
        如果所有后端都失败，抛出最后一个异常
    """
    candidates = await get_backend_candidates_for_model(model_name)
    if not candidates:
        raise HTTPException(status_code=404, detail=f"未找到模型: {model_name}")
    
    last_exception = None
    for i, (router_name, backend_config, actual_model) in enumerate(candidates):
        try:
            logger.info(f"尝试后端 {i+1}/{len(candidates)}: {router_name}")
            
            if router_name == "local":
                # 本地Ollama处理
                local_config = config_loader.get_local_ollama_config()
                base_url = local_config.get("base_url", "http://localhost:11434")
                # 检查Ollama是否可用
                ollama_available = await check_ollama_available()
                if not ollama_available:
                    logger.info(f"Ollama不可用，使用模拟路由器处理本地模型请求: {model_name}")
                    router_name = "mock"
            
            # 通过后端路由器处理
            response = await backend_manager.handle_request(
                router_name,
                actual_model,
                request_data,
                stream,
                convert_to_ollama=convert_to_ollama,
                virtual_model=model_name,
                support_thinking=support_thinking
            )
            logger.info(f"后端 {router_name} 请求成功")
            return response
        except Exception as e:
            logger.warning(f"后端 {router_name} 请求失败: {type(e).__name__}: {e}")
            last_exception = e
            continue
    
    # 所有后端都失败
    logger.error(f"所有后端都失败，最后一个错误: {last_exception}")
    if isinstance(last_exception, HTTPException):
        raise last_exception
    else:
        raise HTTPException(status_code=500, detail=f"所有后端请求失败: {str(last_exception)}")


# ============ 启动事件 ============

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    # 加载配置
    if not config_loader.load():
        logger.warning("配置加载失败，使用默认配置")
    
    # 初始化后端路由器
    init_backend_routers()
    
    # 获取代理配置
    proxy_config = config_loader.get_proxy_config()
    port = proxy_config.get("port", 11435)
    host = proxy_config.get("host", "0.0.0.0")
    
    logger.info("=" * 60)
    logger.info("🤖 智能 Ollama 多模型路由代理")
    logger.info("=" * 60)
    logger.info(f"📡 代理服务运行在: http://{host}:{port}")
    logger.info(f"🔧 配置文件: config.yaml")
    logger.info(f"📊 已加载模型组: {len(config_loader.models)} 个")
    logger.info(f"🔌 后端路由器: {len(backend_manager.routers)} 个")
    
    # 显示已配置的模型
    virtual_models = config_loader.get_all_virtual_models()
    logger.info(f"✨ 虚拟模型: {len(virtual_models)} 个")
    
    logger.info("")
    logger.info("💡 请在 Copilot 中配置 Ollama 地址为上述代理地址")
    logger.info("=" * 60)
    
    yield  # 应用运行期间
    
    # 关闭时清理资源
    logger.info("正在关闭服务...")
    # 关闭ClientPool中的所有HTTP客户端
    from client_pool import client_pool
    await client_pool.close_all()

# 创建FastAPI应用（使用 lifespan 事件处理器）
app = FastAPI(title="Smart Ollama Proxy - 多模型路由", lifespan=lifespan)


# ============ API端点 ============

@app.get("/api/tags")
async def get_models(request: Request):
    """获取合并的模型列表（本地+虚拟）"""
    try:
        # 记录请求详细信息
        client_host = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        logger.info(f"收到 /api/tags 请求 - 客户端: {client_host}, User-Agent: {user_agent}")
        
        combined_models = await model_router.get_combined_models()
        result = {"models": combined_models}
        
        # 记录详细的返回信息
        local_count = sum(1 for m in combined_models if m.get("details", {}).get("format") != "api")
        virtual_count = sum(1 for m in combined_models if m.get("details", {}).get("format") == "api")
        
        logger.info(f"返回 /api/tags: 总共 {len(combined_models)} 个模型 (本地: {local_count}, 虚拟: {virtual_count})")
        logger.debug(f"/api/tags 返回数据示例: {result['models'][:2] if len(result['models']) > 2 else result}")
        
        return result
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}", exc_info=True)
        # 即使失败也返回空列表而不是抛出异常，确保Copilot不会看到错误
        return {"models": []}


@app.post("/api/generate")
async def generate(request: OllamaGenerateRequest):
    """Ollama生成请求"""
    import time
    start_time = time.time()
    
    try:
        # 获取后端配置以检查是否记录完整流式数据
        candidates = await get_backend_candidates_for_model(request.model)
        log_full_data = False
        
        if candidates:
            router_name, backend_config, actual_model = candidates[0]  # 使用第一个候选
            if backend_config and hasattr(backend_config, 'log_full_stream_data'):
                log_full_data = backend_config.log_full_stream_data
        
        # 记录请求输入（根据配置优化日志）
        if not request.stream or log_full_data:
            # 非流式请求或配置了记录完整流式数据时记录详细信息
            logger.debug("=" * 80)
            logger.debug(f"[OLLAMA /api/generate] 收到请求")
            logger.debug(f"模型: {request.model}")
            logger.debug(f"流式: {request.stream}")
            if log_full_data or not request.stream:
                logger.debug(f"Prompt: {request.prompt[:500]}{'...' if len(request.prompt) > 500 else ''}")
                logger.debug(f"完整Prompt长度: {len(request.prompt)} 字符")
                if VERBOSE_JSON_LOGGING:
                    logger.debug(f"Options: {json.dumps(request.options, ensure_ascii=False)}")
                else:
                    logger.debug(f"Options: {request.options}")
            logger.debug("-" * 80)
        else:  # 流式请求且不记录完整数据时只记录基本信息
            logger.info(f"[OLLAMA /api/generate] 收到流式请求，模型: {request.model}")
        
        logger.info(f"收到生成请求，模型: {request.model}, 流式: {request.stream}")
        
        # 获取后端路由器
        router_start = time.time()
        router_info = await get_backend_router_for_model(request.model)
        router_time = time.time() - router_start
        logger.info(f"路由查找耗时: {router_time:.3f}秒")
        
        if not router_info:
            raise HTTPException(status_code=404, detail=f"未找到模型: {request.model}")
        
        router_name, backend_config, actual_model = router_info
        
        # 检查模型是否支持 thinking 能力
        support_thinking = False
        model_info = config_loader.get_model_config(request.model)
        if model_info:
            model_config, virtual_model = model_info
            capabilities = model_config.get_model_capabilities(virtual_model)
            if "thinking" in capabilities:
                support_thinking = True
        
        if router_name == "local":
            # 检查Ollama是否可用
            ollama_available = await check_ollama_available()
            
            if not ollama_available:
                logger.info(f"Ollama不可用，使用模拟路由器处理本地模型请求: {request.model}")
                # 使用mock路由器
                router_name = "mock"
            
            # 本地Ollama请求
            local_config = config_loader.get_local_ollama_config()
            base_url = local_config.get("base_url", "http://localhost:11434")
            
            # 准备请求数据
            ollama_data = {
                "model": request.model,
                "prompt": request.prompt,
                "stream": request.stream,
                "options": request.options
            }
            
            logger.debug(f"[OLLAMA /api/generate] 发送到本地Ollama")
            if VERBOSE_JSON_LOGGING:
                logger.debug(f"请求数据: {json.dumps(ollama_data, ensure_ascii=False, indent=2)}")
            else:
                logger.debug(f"请求数据概要: 模型={ollama_data['model']}, 流式={ollama_data['stream']}, prompt长度={len(ollama_data['prompt'])}")
            
            # 通过路由器处理
            request_start = time.time()
            response = await backend_manager.handle_request(
                router_name,
                actual_model,
                ollama_data,
                request.stream,
                convert_to_ollama=False,  # 本地响应已经是Ollama格式
                virtual_model=request.model,
                support_thinking=support_thinking
            )
            request_time = time.time() - request_start
            logger.info(f"后端请求耗时: {request_time:.3f}秒")
            
            total_time = time.time() - start_time
            logger.info(f"[OLLAMA /api/generate] 总耗时: {total_time:.3f}秒")
            logger.debug("=" * 80)
            
            return response
        else:
            # OpenAI兼容后端请求
            # 准备OpenAI格式请求数据
            openai_data = {
                "messages": [{"role": "user", "content": request.prompt}],
                "stream": request.stream,
                "temperature": request.options.get("temperature", 0.7),
                "max_tokens": request.options.get("num_predict", 2048),
            }
            
            logger.debug(f"[OLLAMA /api/generate] 转换为OpenAI格式并发送到后端")
            logger.debug(f"路由器: {router_name}, 实际模型: {actual_model}")
            if VERBOSE_JSON_LOGGING:
                logger.debug(f"请求数据: {json.dumps(openai_data, ensure_ascii=False, indent=2)}")
            else:
                logger.debug(f"请求数据概要: 消息数={len(openai_data.get('messages', []))}, 流式={openai_data.get('stream', False)}")
            
            # 通过后端路由器处理
            request_start = time.time()
            response = await backend_manager.handle_request(
                router_name,
                actual_model,
                openai_data,
                request.stream,
                convert_to_ollama=(not request.stream),  # 非流式需要转换
                virtual_model=request.model,
                support_thinking=support_thinking
            )
            request_time = time.time() - request_start
            logger.info(f"后端请求耗时: {request_time:.3f}秒")
            
            total_time = time.time() - start_time
            logger.info(f"[OLLAMA /api/generate] 总耗时: {total_time:.3f}秒")
            logger.debug("=" * 80)
            
            return response
            
    except Exception as e:
        total_time = time.time() - start_time if 'start_time' in locals() else 0
        logger.error(f"处理生成请求失败: {e} (耗时: {total_time:.3f}秒)")
        logger.debug("=" * 80)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI兼容聊天完成端点"""
    import time
    start_time = time.time()
    
    try:
        # 获取请求体，处理可能的 Unicode 编码问题
        try:
            body = await request.json()
        except Exception as e:
            # 如果 JSON 解析失败，尝试读取原始数据并清理
            logger.warning(f"JSON 解析失败，尝试清理: {e}")
            raw_body = await request.body()
            try:
                # 尝试使用 UTF-8 解码，替换无效字符
                cleaned_body = raw_body.decode('utf-8', errors='replace')
                body = json.loads(cleaned_body)
            except Exception as e2:
                logger.error(f"无法解析请求体: {e2}")
                raise HTTPException(status_code=400, detail=f"无效的 JSON 请求: {str(e2)}")
        
        model_name = body.get("model", "")
        stream = body.get("stream", False)
        messages = body.get("messages", [])
        
        # 获取后端配置以检查是否记录完整流式数据
        router_info = await get_backend_router_for_model(model_name)
        log_full_data = False
        
        if router_info:
            router_name, backend_config, actual_model = router_info
            if backend_config and hasattr(backend_config, 'log_full_stream_data'):
                log_full_data = backend_config.log_full_stream_data
        
        # 记录请求输入（根据配置优化日志）
        if not stream or log_full_data:
            # 非流式请求或配置了记录完整流式数据时记录详细信息
            logger.debug("=" * 80)
            logger.debug(f"[OPENAI /v1/chat/completions] 收到请求")
            logger.debug(f"模型: {model_name}")
            logger.debug(f"流式: {stream}")
            logger.debug(f"消息数量: {len(messages)}")
            
            if log_full_data or not stream:
                # 记录消息内容（截断长消息）
                for i, msg in enumerate(messages):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    content_preview = content[:200] + "..." if len(content) > 200 else content
                    logger.debug(f"消息[{i}] - Role: {role}, Content长度: {len(content)}, 预览: {content_preview}")
                
                if VERBOSE_JSON_LOGGING:
                    logger.debug(f"完整请求体: {json.dumps(body, ensure_ascii=False, indent=2)}")
                else:
                    logger.debug(f"请求体概要: 模型={model_name}, 流式={stream}, 消息数={len(messages)}")
            
            logger.debug("-" * 80)
        else:
            # 流式请求且不记录完整数据时只记录基本信息
            logger.info(f"[OPENAI /v1/chat/completions] 收到流式请求，模型: {model_name}, 消息数: {len(messages)}")
        
        logger.info(f"收到OpenAI聊天请求，模型: {model_name}, 流式: {stream}, 消息数: {len(messages)}")
        
        # 获取后端路由器
        router_start = time.time()
        router_info = await get_backend_router_for_model(model_name)
        router_time = time.time() - router_start
        logger.info(f"路由查找耗时: {router_time:.3f}秒")
        
        if not router_info:
            raise HTTPException(status_code=404, detail=f"未找到模型: {model_name}")
        
        router_name, backend_config, actual_model = router_info
        
        # 打印聊天输出信息
        logger.info(f"OpenAI聊天路由信息 - 模型: {model_name}, 路由器: {router_name}, 实际模型: {actual_model}")
        if backend_config:
            logger.info(f"后端配置 - URL: {backend_config.base_url}, 超时: {backend_config.timeout}")
            logger.debug(f"后端配置详情: base_url={backend_config.base_url}, timeout={backend_config.timeout}")
        
        # 检查模型是否支持 thinking 能力
        support_thinking = False
        model_info = config_loader.get_model_config(model_name)
        if model_info:
            model_config, virtual_model = model_info
            capabilities = model_config.get_model_capabilities(virtual_model)
            if "thinking" in capabilities:
                support_thinking = True

        logger.debug(f"[OPENAI /v1/chat/completions] 发送到后端路由器")
        logger.debug(f"路由器: {router_name}, 实际模型: {actual_model}, support_thinking: {support_thinking}")

        # 性能监控：转发前耗时（从接收到请求到转发前）
        pre_forward_time = time.time() - start_time
        logger.info(f"[OPENAI /v1/chat/completions] 转发前耗时: {pre_forward_time:.3f}秒")

        # 通过后端路由器处理
        forward_start = time.time()
        logger.info(f"[OPENAI /v1/chat/completions] 开始转发到后端")
        response = await backend_manager.handle_request(
            router_name,
            actual_model,
            body,
            stream,
            convert_to_ollama=False,  # OpenAI端点不需要转换
            virtual_model=model_name,
            support_thinking=support_thinking
        )
        forward_time = time.time() - forward_start
        logger.info(f"[OPENAI /v1/chat/completions] 后端转发耗时: {forward_time:.3f}秒")
        
        # 记录响应（如果是非流式响应）
        if not stream and hasattr(response, 'body'):
            try:
                if isinstance(response.body, bytes):
                    response_data = json.loads(response.body.decode())
                    logger.debug(f"[OPENAI /v1/chat/completions] 响应数据:")
                    if VERBOSE_JSON_LOGGING:
                        logger.debug(f"{json.dumps(response_data, ensure_ascii=False, indent=2)}")
                    else:
                        # 只打印关键信息
                        choices = response_data.get('choices', [])
                        if choices:
                            first_choice = choices[0]
                            message = first_choice.get('message', {})
                            content = message.get('content', '')
                            finish_reason = first_choice.get('finish_reason', 'unknown')
                            logger.debug(f"响应概要: 选择数={len(choices)}, 内容长度={len(content)}, 完成原因={finish_reason}")
                        else:
                            logger.debug(f"响应概要: 无选择数据")
            except:
                logger.debug(f"[OPENAI /v1/chat/completions] 无法解析响应数据")
        
        total_time = time.time() - start_time
        logger.info(f"[OPENAI /v1/chat/completions] 总耗时: {total_time:.3f}秒")
        logger.debug("=" * 80)
        
        return response
            
    except Exception as e:
        total_time = time.time() - start_time if 'start_time' in locals() else 0
        logger.error(f"处理OpenAI聊天请求失败: {e} (耗时: {total_time:.3f}秒)")
        logger.debug("=" * 80)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/version")
async def get_version():
    """获取版本信息"""
    local_config = config_loader.get_local_ollama_config()
    base_url = local_config.get("base_url", "http://localhost:11434")
    
    # 使用更短的超时时间，快速失败
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}/api/version")
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning(f"获取Ollama版本失败，状态码: {resp.status_code}")
                # 返回模拟版本
                return {"version": "0.6.4", "mock": True, "message": "Ollama不可用，使用模拟版本"}
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.warning(f"连接Ollama失败，返回模拟版本: {type(e).__name__}")
        # 返回模拟版本
        return {"version": "0.6.4", "mock": True, "message": "Ollama不可用，使用模拟版本"}
    except Exception as e:
        logger.warning(f"获取Ollama版本失败，返回模拟版本: {type(e).__name__}")
        # 返回模拟版本
        return {"version": "0.6.4", "mock": True, "message": "Ollama不可用，使用模拟版本"}


@app.post("/api/show")
async def show_model(request: Request):
    """获取模型信息"""
    try:
        body = await request.json()
        model_name = body.get("model", "")
        
        logger.info(f"收到模型信息请求: {model_name}")
        
        # 检查是否为虚拟模型
        model_info = config_loader.get_model_config(model_name)
        if model_info:
            model_config, virtual_model = model_info
            
            # 如果是虚拟模型，返回虚拟模型信息
            if model_config.model_group != "local":
                # 构建完整的模型名（带组名）
                full_model_name = f"{model_config.model_group}/{virtual_model}" if '/' not in model_name else model_name
                logger.info(f"返回虚拟模型信息: {full_model_name} (组: {model_config.model_group}, 虚拟模型: {virtual_model})")
                
                # 获取后端配置以填充remote_host和remote_model
                remote_host = ""
                remote_model = virtual_model
                backend_mode = config_loader.routing_config.get("default_backend_mode", "openai_backend")
                backend = model_config.get_backend(backend_mode)
                if backend:
                    remote_host = backend.base_url
                    actual_model = model_config.get_actual_model(virtual_model, backend_mode)
                    if actual_model:
                        remote_model = actual_model
                
                # 构建模型信息（模仿云模型结构）
                model_info = {
                    "general.architecture": model_config.model_group,
                    "general.basename": remote_model,
                    f"{model_config.model_group}.context_length": model_config.get_model_context_length(virtual_model),
                    f"{model_config.model_group}.embedding_length": model_config.get_model_embedding_length(virtual_model)
                }
                
                # 能力列表
                capabilities = model_config.get_model_capabilities(virtual_model)
                
                return {
                    "model": full_model_name,  # 返回带组名的完整模型名
                    "details": {
                        "parent_model": "",
                        "format": "api",
                        "family": model_config.model_group,
                        "families": [model_config.model_group],
                        "parameter_size": "7B",
                        "quantization_level": "FP8_E4M3"
                    },
                    "modelfile": f"# Virtual {model_config.model_group} model via API\nFROM api:{model_config.model_group}\n\nSYSTEM \"You are a helpful AI assistant.\"",
                    "template": "{{ .Prompt }}",
                    "parameters": "num_ctx 4096\nnum_predict 2048\ntemperature 0.7",
                    "license": "",
                    "system": "You are a helpful AI assistant.",
                    "remote_model": remote_model,
                    "remote_host": remote_host,
                    "model_info": model_info,
                    "capabilities": capabilities,
                    "modified_at": "2026-01-14T05:40:00.000000+08:00"
                }
            else:
                logger.info(f"模型 {model_name} 属于本地组，转发到本地Ollama")
        else:
            logger.info(f"模型 {model_name} 未在配置中找到，尝试作为本地模型处理")
        
        # 转发到本地Ollama，如果失败则返回模拟响应
        local_config = config_loader.get_local_ollama_config()
        base_url = local_config.get("base_url", "http://localhost:11434")
        
        try:
            logger.info(f"转发 /api/show 请求到本地Ollama: {base_url}/api/show")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{base_url}/api/show", json=body)
                logger.info(f"本地Ollama /api/show 响应状态码: {response.status_code}")
                
                if response.status_code == 200:
                    response_data = response.json()
                    logger.debug(f"本地Ollama返回的模型信息: {response_data.get('model', 'unknown')}")
                    return response_data
                else:
                    error_text = await response.aread() if response.content else "无响应内容"
                    logger.warning(f"本地Ollama /api/show 返回错误: {response.status_code}, {error_text[:100]}")
        except Exception as e:
            logger.warning(f"连接本地Ollama失败: {type(e).__name__}: {e}")
        
        # 返回模拟响应
        logger.info(f"为模型 {model_name} 返回模拟响应")
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
        logger.error(f"处理模型信息请求失败: {e}", exc_info=True)
        return {
            "model": "",
            "details": {},
            "modelfile": "",
            "template": "",
            "parameters": {},
            "license": "",
            "system": ""
        }


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_ollama(path: str, request: Request):
    """转发其他Ollama API请求，如果Ollama不可用则返回模拟响应"""
    # 排除已经特殊处理的端点
    if path in ["tags", "generate", "version", "show"]:
        # 这些端点已经有特殊处理
        pass
    
    local_config = config_loader.get_local_ollama_config()
    base_url = local_config.get("base_url", "http://localhost:11434")
    target_url = f"{base_url}/api/{path}"
    
    logger.info(f"转发请求 {request.method} /api/{path} -> {target_url}")
    
    # 获取请求体
    body = None
    if request.method in ["POST", "PUT"]:
        body = await request.body()
    
    # 转发请求，如果失败则返回模拟响应
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
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
        logger.warning(f"转发失败 {request.method} /api/{path} -> 返回模拟响应: {str(e)}")
        
        # 根据路径返回不同的模拟响应
        if path == "pull":
            # 模拟拉取模型响应
            return JSONResponse(
                content={"status": "success", "message": "Model pull simulated (Ollama not available)"},
                status_code=200
            )
        elif path == "delete":
            # 模拟删除模型响应
            return JSONResponse(
                content={"status": "success", "message": "Model delete simulated (Ollama not available)"},
                status_code=200
            )
        elif path == "copy":
            # 模拟复制模型响应
            return JSONResponse(
                content={"status": "success", "message": "Model copy simulated (Ollama not available)"},
                status_code=200
            )
        else:
            # 通用模拟响应
            return JSONResponse(
                content={
                    "error": f"Ollama not available: {path}",
                    "mock": True,
                    "message": "Ollama is not available, this is a simulated response"
                },
                status_code=200
            )


@app.get("/api/client-pool")
async def get_client_pool_status():
    """获取ClientPool状态信息"""
    from client_pool import client_pool
    stats = client_pool.get_stats()
    
    return {
        "message": "ClientPool状态",
        "stats": stats,
        "description": "HTTP客户端池管理器，用于复用相同后端配置的HTTP客户端"
    }


@app.get("/")
async def root():
    """根端点，显示服务信息"""
    proxy_config = config_loader.get_proxy_config()
    local_config = config_loader.get_local_ollama_config()
    
    # 获取模型组信息
    model_groups = list(config_loader.models.keys())
    backend_routers = list(backend_manager.routers.keys())
    
    return {
        "message": "Smart Ollama Proxy - 多模型路由代理",
        "version": "2.0.0",
        "architecture": "模型选择 -> 后端模式 -> 模型后端",
        "endpoints": {
            "GET /api/tags": "获取合并后的模型列表",
            "POST /api/generate": "智能路由生成请求",
            "POST /v1/chat/completions": "OpenAI兼容聊天完成",
            "GET /api/version": "获取版本信息",
            "POST /api/show": "获取模型信息",
            "ANY /api/{path}": "转发其他Ollama API请求"
        },
        "config": {
            "proxy_port": proxy_config.get("port", 11435),
            "local_ollama": local_config.get("base_url", "http://localhost:11434"),
            "model_groups": model_groups,
            "backend_routers": backend_routers
        }
    }


# ============ 主程序 ============

if __name__ == "__main__":
    import uvicorn
    
    # 加载配置
    if not config_loader.load():
        logger.warning("配置加载失败，使用默认配置")
    
    # 初始化后端路由器
    init_backend_routers()
    
    proxy_config = config_loader.get_proxy_config()
    port = proxy_config.get("port", 11435)
    host = proxy_config.get("host", "0.0.0.0")
    
    uvicorn.run(app, host=host, port=port)