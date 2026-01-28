"""
模拟后端路由器
用于在没有真实后端时提供模拟响应
重构版：使用基类组件减少重复代码
"""
import logging
import asyncio
from utils import json
import time
import uuid
from typing import Dict, Any

from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import HTTPException

from config_loader import BackendConfig
from .base_router import BackendRouter

# 导入智能日志处理器
from smart_logger import get_smart_logger
smart_logger = get_smart_logger()

logger = logging.getLogger("smart_ollama_proxy.backend_router")


class MockBackendRouter(BackendRouter):
    """模拟后端路由器，用于在没有真实后端时提供模拟响应（重构版）"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config, verbose_json_logging,  # type: ignore
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        self.mock_responses = {
            "generate": {
                "model": "mock-model",
                "response": "这是一个模拟响应。由于没有安装Ollama，我无法提供真实的AI回复。请安装Ollama或配置其他后端服务。",
                "done": True,
                "total_duration": 1000000000,
            },
            "chat": {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "这是一个模拟响应。由于没有安装Ollama，我无法提供真实的AI回复。请安装Ollama或配置其他后端服务。"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30
                }
            }
        }
    
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理模拟请求"""
        logger.info(f"模拟后端处理请求，模型: {actual_model}, 流式: {stream}")
        
        # 判断请求类型
        if "messages" in request_data:
            # OpenAI格式请求
            response_type = "chat"
        else:
            # Ollama格式请求
            response_type = "generate"
        
        # 如果是流式请求，返回流式响应
        if stream:
            async def mock_stream():
                chunk_count = 0
                total_bytes = 0
                spinner_idx = 0
                content_length = None
                
                # 生成日志ID（用于关联流式进度和完成日志）
                log_id = uuid.uuid4().hex
                
                if response_type == "chat":
                    # OpenAI流式格式
                    mock_data = self.mock_responses["chat"]
                    content = mock_data["choices"][0]["message"]["content"]
                    words = content.split()
                    for i, word in enumerate(words):
                        chunk = {
                            "id": "chatcmpl-mock",
                            "object": "chat.completion.chunk",
                            "created": 1700000000,
                            "model": actual_model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": word + " "},
                                    "finish_reason": None if i < len(words) - 1 else "stop"
                                }
                            ]
                        }
                        chunk_json = json.dumps(chunk)
                        chunk_bytes = len(chunk_json.encode('utf-8'))
                        chunk_count += 1
                        total_bytes += chunk_bytes
                        spinner_idx = self._print_stream_progress(
                            chunk_count, total_bytes, content_length, spinner_idx, log_id
                        )
                        yield f"data: {chunk_json}\n\n"
                        await asyncio.sleep(0.05)
                    
                    # 流式完成
                    self._print_stream_complete(chunk_count, total_bytes, log_id)
                    yield "data: [DONE]\n\n"
                else:
                    # Ollama流式格式
                    mock_data = self.mock_responses["generate"]
                    content = mock_data["response"]
                    words = content.split()
                    for i, word in enumerate(words):
                        chunk = {
                            "model": actual_model,
                            "response": word + " ",
                            "done": i == len(words) - 1
                        }
                        chunk_json = json.dumps(chunk)
                        chunk_bytes = len(chunk_json.encode('utf-8'))
                        chunk_count += 1
                        total_bytes += chunk_bytes
                        spinner_idx = self._print_stream_progress(
                            chunk_count, total_bytes, content_length, spinner_idx, log_id
                        )
                        yield chunk_json + "\n"
                        await asyncio.sleep(0.05)
                    
                    # 流式完成
                    self._print_stream_complete(chunk_count, total_bytes, log_id)
            
            if response_type == "chat":
                return StreamingResponse(mock_stream(), media_type="text/event-stream")
            else:
                return StreamingResponse(mock_stream(), media_type="application/x-ndjson")
        
        # 非流式请求
        else:
            if response_type == "chat":
                mock_data = self.mock_responses["chat"].copy()
                mock_data["model"] = actual_model
                return JSONResponse(content=mock_data)
            else:
                mock_data = self.mock_responses["generate"].copy()
                mock_data["model"] = actual_model
                return JSONResponse(content=mock_data)
    
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """将模拟响应转换为Ollama格式"""
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