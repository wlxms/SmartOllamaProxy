#!/usr/bin/env python3
"""
测试LiteLLM序列化功能
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import Mock, MagicMock
from routers.litellm_router import LiteLLMRouter
from config_loader import BackendConfig


class TestLiteLLMSerialization(unittest.TestCase):
    """测试LiteLLM序列化功能"""
    
    def setUp(self):
        """设置测试环境"""
        config_data = {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "test-key",
            "backend_mode": "litellm_backend"
        }
        config = BackendConfig(config_data)
        self.router = LiteLLMRouter(config, verbose_json_logging=False)
    
    def test_safe_chunk_to_dict_with_dict(self):
        """测试_safe_chunk_to_dict处理字典输入"""
        # 测试字典输入
        test_dict = {"choices": [{"index": 0, "delta": {"content": "Hello"}}]}
        result = self.router._safe_chunk_to_dict(test_dict)
        self.assertEqual(result, test_dict)
    
    def test_safe_chunk_to_dict_with_object(self):
        """测试_safe_chunk_to_dict处理对象输入"""
        # 创建对象，有to_dict方法
        class ObjectWithToDict:
            def to_dict(self):
                return {"test": "value"}
        
        obj = ObjectWithToDict()
        result = self.router._safe_chunk_to_dict(obj)
        self.assertEqual(result, {"test": "value"})
    
    def test_safe_chunk_to_dict_with_streaming_choices(self):
        """测试_safe_chunk_to_dict处理StreamingChoices对象"""
        # 模拟StreamingChoices对象（没有to_dict方法）
        class MockStreamingChoices:
            def __init__(self):
                self.choices = [Mock()]
                self.choices[0].index = 0
                self.choices[0].delta = Mock()
                self.choices[0].delta.content = "Hello"
        
        mock_chunk = MockStreamingChoices()
        
        # 使用vars()应该能获取属性
        result = self.router._safe_chunk_to_dict(mock_chunk)
        # 结果应该包含choices属性
        self.assertIn("choices", result)
    
    def test_safe_chunk_to_dict_with_pydantic_model(self):
        """测试_safe_chunk_to_dict处理Pydantic模型"""
        # 模拟Pydantic模型（有dict方法，没有to_dict方法）
        class PydanticLike:
            def dict(self):
                return {"pydantic": "data"}
        
        obj = PydanticLike()
        result = self.router._safe_chunk_to_dict(obj)
        self.assertEqual(result, {"pydantic": "data"})
    
    def test_safe_chunk_to_dict_fallback_to_str(self):
        """测试_safe_chunk_to_dict回退到字符串表示"""
        # 创建无法转换的对象：没有to_dict，dict()失败，vars()失败
        class Unconvertible:
            __slots__ = ()  # 没有__dict__，vars()会失败
            
            def __str__(self):
                return '{"test": "value"}'
            
            # dict()会尝试调用__iter__或items()，我们都不提供
        
        obj = Unconvertible()
        result = self.router._safe_chunk_to_dict(obj)
        # 应该尝试解析字符串表示
        self.assertEqual(result, {"test": "value"})
    
    def test_safe_chunk_to_dict_error_handling(self):
        """测试_safe_chunk_to_dict错误处理"""
        # 创建引发异常的对象：没有to_dict，dict()失败，vars()失败，__str__也失败
        class ErrorObject:
            __slots__ = ()  # 没有__dict__，vars()会失败
            
            def __str__(self):
                raise Exception("Test error")
            
            # dict()会尝试调用__iter__或items()，我们都不提供
        
        obj = ErrorObject()
        result = self.router._safe_chunk_to_dict(obj)
        # 应该返回错误信息字典
        self.assertIn("_error", result)
    
    def test_safe_response_to_dict_with_dict(self):
        """测试_safe_response_to_dict处理字典输入"""
        test_dict = {"id": "test", "choices": []}
        result = self.router._safe_response_to_dict(test_dict)
        self.assertEqual(result, test_dict)
    
    def test_safe_response_to_dict_with_object(self):
        """测试_safe_response_to_dict处理对象输入"""
        # 创建对象，有to_dict方法
        class ObjectWithToDict:
            def to_dict(self):
                return {"response": "data"}
        
        obj = ObjectWithToDict()
        result = self.router._safe_response_to_dict(obj)
        self.assertEqual(result, {"response": "data"})
    
    def test_safe_response_to_dict_fallback(self):
        """测试_safe_response_to_dict回退机制"""
        # 创建没有to_dict方法的对象
        class SimpleObject:
            def __init__(self):
                self.field1 = "value1"
                self.field2 = "value2"
        
        obj = SimpleObject()
        result = self.router._safe_response_to_dict(obj)
        # 应该使用vars()获取属性
        self.assertEqual(result["field1"], "value1")
        self.assertEqual(result["field2"], "value2")
    
    def test_type_annotations(self):
        """测试类型注解是否正确"""
        # 验证方法有正确的类型注解
        import inspect
        from typing import Dict, Any
        
        # 检查_safe_chunk_to_dict
        sig1 = inspect.signature(self.router._safe_chunk_to_dict)
        self.assertEqual(sig1.return_annotation, Dict[str, Any])
        
        # 检查_safe_response_to_dict
        sig2 = inspect.signature(self.router._safe_response_to_dict)
        self.assertEqual(sig2.return_annotation, Dict[str, Any])


if __name__ == "__main__":
    unittest.main()