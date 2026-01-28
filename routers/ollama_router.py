"""
Ollama后端路由器
用于本地Ollama服务
重构版：使用基类组件减少重复代码
"""
import logging
import time
import uuid
from utils import json
from typing import Dict, Any, Optional

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config_loader import BackendConfig
from client_pool import client_pool
from .base_router import BackendRouter

# 导入智能日志处理器
from smart_logger import get_smart_logger
smart_logger = get_smart_logger()

logger = logging.getLogger("smart_ollama_proxy.backend_router")


class OllamaBackendRouter(BackendRouter):
    """Ollama后端路由器（用于本地Ollama，重构版）"""
    
    def __init__(self, backend_config: BackendConfig, base_url: str = "http://localhost:11434",
                 verbose_json_logging: bool = False, tool_compression_enabled: bool = True,
                 prompt_compression_enabled: bool = True):
        super().__init__(backend_config, verbose_json_logging,  # type: ignore
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        self.base_url = base_url
        # HTTP客户端（延迟初始化）
        self._client: Optional[httpx.AsyncClient] = None
    
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理Ollama请求"""
        # 确定端点
        if "messages" in request_data:
            # OpenAI格式请求
            endpoint = "v1/chat/completions"
        else:
            # Ollama格式请求
            endpoint = "api/generate"
            # 确保有model字段
            if "model" not in request_data:
                request_data["model"] = actual_model
        
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        # 从ClientPool获取客户端
        if self._client is None:
            self._client = await client_pool.get_client(
                base_url=self.base_url,
                api_key=None,
                timeout=self.config.timeout,
                compression=self.config.compression_enabled
            )
        
        # 确保客户端已初始化
        if self._client is None:
            logger.error(f"[OllamaBackendRouter] 无法获取HTTP客户端")
            raise HTTPException(status_code=500, detail="无法初始化HTTP客户端")
        
        # 处理流式响应
        if stream:
            # 准备请求头
            headers = {"Content-Type": "application/json"}
            # 根据端点确定媒体类型和格式
            if endpoint == "api/generate":
                media_type = "application/x-ndjson"
                is_sse_format = False
                chunk_end_marker = b'\n'
            else:
                media_type = "text/event-stream"
                is_sse_format = True
                chunk_end_marker = b'\n\n'
            
            # 使用通用流式处理方法
            return await self._handle_stream_generic(
                url=url,
                data=request_data,
                headers=headers,
                media_type=media_type,
                is_sse_format=is_sse_format,
                chunk_end_marker=chunk_end_marker,
                model_name=actual_model,
                router_name=self.__class__.__name__
            )
        
        # 处理非流式响应
        else:
            try:
                # 确保客户端已初始化
                if self._client is None:
                    logger.error(f"[OllamaBackendRouter] HTTP客户端未初始化")
                    raise HTTPException(status_code=500, detail="HTTP客户端未初始化")
                
                # 使用从ClientPool获取的客户端（性能优化）
                response = await self._client.post(url, json=request_data)
                
                if response.status_code != 200:
                    raise HTTPException(status_code=response.status_code, detail=response.text)
                
                return JSONResponse(content=response.json())
            except Exception as e:
                logger.error(f"Ollama请求失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))
    
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """Ollama响应已经是Ollama格式，直接返回或转换"""
        if isinstance(response_data, dict):
            return response_data
        elif hasattr(response_data, 'body'):
            # JSONResponse对象
            body = response_data.body
            if isinstance(body, bytes):
                return json.loads(body.decode())
            else:
                return body
        else:
            raise ValueError(f"无法处理的响应类型: {type(response_data)}")
    
    async def _handle_stream_generic(
        self,
        url: str,
        data: Dict[str, Any],
        headers: Dict[str, str],
        media_type: str = "text/event-stream",
        is_sse_format: bool = True,
        chunk_end_marker: bytes = b'\n\n',
        model_name: str = "",
        router_name: str = ""
    ) -> StreamingResponse:
        """
        通用的流式请求处理方法（优化版）
        
        Args:
            url: 请求URL
            data: 请求数据
            headers: 请求头
            media_type: 媒体类型
            is_sse_format: 是否为SSE格式（data:前缀）
            chunk_end_marker: 块结束标记
            model_name: 模型名称，用于日志记录
            router_name: 路由器名称，用于日志记录
            
        Returns:
            StreamingResponse对象
        """
        stream_start = time.time()
        chunk_count = 0
        
        async def generic_stream():
            nonlocal chunk_count
            try:
                logger.debug(f"[{self.__class__.__name__}] 开始通用流式请求（优化版）")
                
                # 生成日志ID（用于关联流式进度和完成日志）
                log_id = uuid.uuid4().hex
                # 记录输入流（请求数据）
                smart_logger.data.record(
                    key="input",
                    value={
                        "data": data,
                        "summary": f"输入流 - 路由器: {router_name or self.__class__.__name__}, 模型: {model_name or data.get('model', 'unknown')}",
                        "router": router_name or self.__class__.__name__,
                        "model_name": model_name or data.get("model", "unknown"),
                        "stream": True,
                        "log_id": log_id
                    }
                )
                
                connect_start = time.time()
                
                # 优化JSON序列化 - 使用更高效的参数
                try:
                    json_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
                except (UnicodeEncodeError, ValueError) as e:
                    logger.warning(f"流式请求 JSON 序列化失败，尝试清理数据: {e}")
                    # 如果序列化失败，尝试清理数据后重试
                    cleaned_data = self._clean_request_data(data)
                    json_data = json.dumps(cleaned_data, ensure_ascii=False, separators=(',', ':'))
                
                # 确保客户端已初始化
                if not hasattr(self, '_client') or self._client is None:
                    logger.error(f"[{self.__class__.__name__}] HTTP客户端未初始化")
                    error_data = json.dumps({"error": "HTTP客户端未初始化"})
                    if is_sse_format:
                        yield f"data: {error_data}\n\n".encode('utf-8')
                    else:
                        yield error_data.encode('utf-8')
                    return
                
                # 使用客户端发送请求
                async with self._client.stream(
                    "POST",
                    url,
                    content=json_data.encode('utf-8'),
                    headers=headers
                ) as response:
                    connect_time = time.time() - connect_start
                    logger.info(f"[{self.__class__.__name__}] 连接建立耗时: {connect_time:.3f}秒")
                    logger.debug(f"[{self.__class__.__name__}] 响应状态码: {response.status_code}")
                    
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(f"[{self.__class__.__name__}] 错误响应: {error_text.decode()}")
                        error_data = json.dumps({'error': error_text.decode()})
                        if is_sse_format:
                            yield f"data: {error_data}\n\n".encode('utf-8')
                        else:
                            yield error_data.encode('utf-8')
                        return
                    
                    first_chunk_time = None
                    chunk_count = 0
                    
                    # 进度显示变量
                    total_bytes_received = 0
                    content_length = response.headers.get('content-length')
                    if content_length:
                        content_length = int(content_length)
                    else:
                        content_length = None
                    
                    spinner_idx = 0
                    
                    # 使用 aiter_bytes() 以提高性能
                    async for chunk in response.aiter_bytes():
                        if first_chunk_time is None:
                            first_chunk_time = time.time() - stream_start
                            logger.info(f"[{self.__class__.__name__}] 首块响应时间: {first_chunk_time:.3f}秒")

                        # 直接转发数据块，不进行缓冲
                        chunk_count += 1
                        total_bytes_received += len(chunk)
                        
                        # 更新进度显示
                        spinner_idx = self._print_stream_progress(
                            chunk_count, total_bytes_received, content_length, spinner_idx, log_id
                        )
                        
                        if is_sse_format and chunk_end_marker in chunk:
                            # 如果已经是SSE格式，直接转发
                            yield chunk
                        elif is_sse_format:
                            # 转换为SSE格式
                            yield f"data: {chunk.decode('utf-8', errors='ignore')}\n\n".encode('utf-8')
                        else:
                            # 非SSE格式，直接转发
                            yield chunk
                    
                    # 流式完成
                    self._print_stream_complete(chunk_count, total_bytes_received, log_id)

                    # 记录统计信息
                    total_time = time.time() - stream_start
                    first_to_all_time = total_time - first_chunk_time if first_chunk_time else 0
                    logger.info(f"[{self.__class__.__name__}] 首块到全部块接收耗时: {first_to_all_time:.3f}秒")
                    logger.info(f"[{self.__class__.__name__}] 流式请求完成，总耗时: {total_time:.3f}秒，接收块数: {chunk_count}，总字节数: {total_bytes_received}")
                    
                    # 结束流式会话，组装并打印完整JSON
                    if log_id:
                        smart_logger.process.info(
                            "流式会话结束",
                            log_id=log_id,
                            event="stream_end"
                        )
                    
                    if is_sse_format:
                        yield b'data: [DONE]\n\n'
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}] 流式请求失败: {e}")
                error_data = json.dumps({"error": str(e)})
                if is_sse_format:
                    yield f"data: {error_data}\n\n".encode('utf-8')
                else:
                    yield error_data.encode('utf-8')
        
        return StreamingResponse(generic_stream(), media_type=media_type)
    
    def _clean_request_data(self, data: Any) -> Any:
        """清理请求数据，处理可能的序列化问题"""
        from utils import sanitize_message
        
        if isinstance(data, dict):
            cleaned = {}
            for key, value in data.items():
                if key == "messages" and isinstance(value, list):
                    # 清理消息列表
                    cleaned_messages = []
                    for msg in value:
                        if isinstance(msg, dict):
                            cleaned_messages.append(sanitize_message(msg))
                        else:
                            cleaned_messages.append(msg)
                    cleaned[key] = cleaned_messages
                else:
                    cleaned[key] = self._clean_request_data(value)
            return cleaned
        elif isinstance(data, list):
            return [self._clean_request_data(item) for item in data]
        elif isinstance(data, str):
            # 清理字符串
            try:
                data.encode('utf-8', errors='strict')
                return data
            except UnicodeEncodeError:
                return data.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        else:
            return data


# 添加类型注解
from typing import Optional