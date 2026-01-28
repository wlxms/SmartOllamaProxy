"""
Response converter for transforming between different API formats.
支持不同API格式之间的转换，如OpenAI到Ollama格式。
"""
import logging
from typing import Dict, Any, Optional
from utils import json

logger = logging.getLogger("smart_ollama_proxy.response_converter")


class ResponseConverter:
    """响应转换器，处理不同后端格式之间的转换"""
    
    @staticmethod
    def convert_to_ollama_format(response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """将OpenAI兼容的响应转换为Ollama格式
        
        Args:
            response_data: 原始响应数据，可以是字典或JSONResponse对象
            virtual_model: 虚拟模型名称，用于Ollama格式中的model字段
            
        Returns:
            Ollama格式的响应字典
        """
        if isinstance(response_data, dict):
            openai_result = response_data
        elif hasattr(response_data, 'body'):
            # JSONResponse对象
            body = response_data.body
            if isinstance(body, bytes):
                openai_result = json.loads(body.decode())
            else:
                openai_result = body
        else:
            raise ValueError(f"无法处理的响应类型: {type(response_data)}")
        
        # 提取消息内容
        choices = openai_result.get("choices", [])
        if not choices:
            # 如果没有choices，可能是Ollama格式，直接返回
            return openai_result
        
        # 转换为Ollama格式
        message = choices[0].get("message", {})
        content = message.get("content", "")
        
        ollama_result = {
            "model": virtual_model,
            "response": content,
            "done": True,
            "total_duration": openai_result.get("usage", {}).get("total_tokens", 0) * 50_000_000,
        }
        return ollama_result
    
    @staticmethod
    def convert_openai_to_ollama(openai_result: Dict[str, Any], virtual_model: str) -> Dict[str, Any]:
        """将OpenAI格式的字典直接转换为Ollama格式（简化版）
        
        Args:
            openai_result: OpenAI格式的响应字典
            virtual_model: 虚拟模型名称
            
        Returns:
            Ollama格式的响应字典
        """
        choices = openai_result.get("choices", [])
        if not choices:
            return {"model": virtual_model, "response": "", "done": True}
        
        message = choices[0].get("message", {})
        content = message.get("content", "")
        
        return {
            "model": virtual_model,
            "response": content,
            "done": True,
            "total_duration": openai_result.get("usage", {}).get("total_tokens", 0) * 50_000_000,
        }
    
    @staticmethod
    def normalize_response(response: Any) -> Dict[str, Any]:
        """将任意响应对象规范化为字典
        
        Args:
            response: 响应对象，可以是字典、JSONResponse、SDK对象等
            
        Returns:
            规范化后的字典
        """
        if isinstance(response, dict):
            return response
        
        if hasattr(response, 'body'):
            # JSONResponse对象
            body = response.body
            if isinstance(body, bytes):
                return json.loads(body.decode())
            else:
                return body
        
        # 尝试使用 model_dump 或 to_dict 方法
        if hasattr(response, 'model_dump'):
            return response.model_dump()
        if hasattr(response, 'to_dict'):
            return response.to_dict()
        if hasattr(response, 'dict'):
            return response.dict()
        
        # 最后手段：转换为字符串并尝试解析
        try:
            return json.loads(str(response))
        except:
            logger.warning(f"无法规范化响应类型: {type(response)}")
            return {"_raw": str(response)}