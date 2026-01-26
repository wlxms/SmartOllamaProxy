#!/usr/bin/env python3
"""
测试新的路由器架构：LiteLLMRouter和OpenAIBackendRouter
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import json
from typing import Dict, Any

from config_loader import ConfigLoader, BackendConfig
from routers.backend_router_factory import BackendRouterFactory
from routers.openai_router import OpenAIBackendRouter
from routers.litellm_router import LiteLLMRouter

def test_config_loading():
    """测试配置加载和解析"""
    print("=== 测试配置加载 ===")
    
    config_loader = ConfigLoader("config.yaml")
    success = config_loader.load()
    assert success, "配置加载失败"
    
    # 检查deepseek模型组是否有两个后端配置
    deepseek_config = config_loader.models.get("deepseek")
    assert deepseek_config is not None, "deepseek模型组未找到"
    
    openai_backend = deepseek_config.get_backend("openai_backend")
    litellm_backend = deepseek_config.get_backend("litellm_backend")
    
    assert openai_backend is not None, "openai_backend配置未找到"
    assert litellm_backend is not None, "litellm_backend配置未找到"
    
    print(f"[OK] deepseek模型组配置:")
    print(f"  - openai_backend: {openai_backend.base_url}")
    print(f"  - litellm_backend: {litellm_backend.base_url}")
    print(f"  - openai_backend.backend_mode: {openai_backend.backend_mode}")
    print(f"  - litellm_backend.backend_mode: {litellm_backend.backend_mode}")
    
    # 验证backend_mode正确设置
    assert openai_backend.backend_mode == "openai_backend"
    assert litellm_backend.backend_mode == "litellm_backend"
    
    return openai_backend, litellm_backend

def test_router_factory():
    """测试路由器工厂"""
    print("\n=== 测试路由器工厂 ===")
    
    # 测试openai_backend配置 -> OpenAIBackendRouter
    openai_config = BackendConfig({
        "base_url": "https://api.example.com/v1",
        "api_key": "test-key"
    }, backend_mode="openai_backend")
    
    openai_router = BackendRouterFactory.create_router(openai_config)
    assert isinstance(openai_router, OpenAIBackendRouter), \
        f"openai_backend应该创建OpenAIBackendRouter，实际是{type(openai_router)}"
    print(f"[OK] openai_backend配置创建了{openai_router.__class__.__name__}")
    
    # 测试litellm_backend配置 -> LiteLLMRouter
    litellm_config = BackendConfig({
        "base_url": "https://api.example.com/v1",
        "api_key": "test-key"
    }, backend_mode="litellm_backend")
    
    litellm_router = BackendRouterFactory.create_router(litellm_config)
    assert isinstance(litellm_router, LiteLLMRouter), \
        f"litellm_backend应该创建LiteLLMRouter，实际是{type(litellm_router)}"
    print(f"[OK] litellm_backend配置创建了{litellm_router.__class__.__name__}")
    
    # 测试显式backend_type
    openai_sdk_config = BackendConfig({
        "base_url": "https://api.example.com/v1",
        "api_key": "test-key",
        "backend_type": "openai_sdk"
    }, backend_mode="openai_backend")
    
    openai_sdk_router = BackendRouterFactory.create_router(openai_sdk_config)
    # 注意：OpenAISDKBackendRouter已整合到OpenAIBackendRouter中
    # backend_type='openai_sdk'现在创建OpenAIBackendRouter
    assert isinstance(openai_sdk_router, OpenAIBackendRouter), \
        f"backend_type='openai_sdk'现在创建OpenAIBackendRouter，实际是{type(openai_sdk_router)}"
    print(f"[OK] backend_type='openai_sdk'创建了{openai_sdk_router.__class__.__name__}")
    
    return openai_router, litellm_router

def test_router_methods():
    """测试路由器方法"""
    print("\n=== 测试路由器方法 ===")
    
    # 创建测试配置
    config = BackendConfig({
        "base_url": "https://api.example.com/v1",
        "api_key": "test-key"
    }, backend_mode="openai_backend")
    
    router = BackendRouterFactory.create_router(config)
    
    # 测试convert_to_ollama_format方法
    mock_response = {
        "choices": [{
            "message": {
                "content": "Hello, world!"
            }
        }],
        "usage": {
            "total_tokens": 10
        }
    }
    
    ollama_result = router.convert_to_ollama_format(mock_response, "test-model")
    
    assert ollama_result["model"] == "test-model"
    assert ollama_result["response"] == "Hello, world!"
    assert ollama_result["done"] == True
    assert "total_duration" in ollama_result
    
    print(f"[OK] convert_to_ollama_format方法测试通过")
    print(f"  转换结果: {json.dumps(ollama_result, ensure_ascii=False, indent=2)}")
    
    return router

def main():
    """主测试函数"""
    print("[TEST] 测试新的路由器架构")
    print("=" * 50)
    
    try:
        # 测试配置加载
        openai_backend, litellm_backend = test_config_loading()
        
        # 测试路由器工厂
        openai_router, litellm_router = test_router_factory()
        
        # 测试路由器方法
        test_router = test_router_methods()
        
        print("\n" + "=" * 50)
        print("[PASS] 所有测试通过！")
        print("\n架构总结:")
        print("1. openai_backend配置 -> OpenAIBackendRouter (OpenAI SDK + HTTP回退)")
        print("2. litellm_backend配置 -> LiteLLMRouter (纯LiteLLM)")
        print("3. backend_type='openai_sdk' -> OpenAIBackendRouter (OpenAI SDK + HTTP回退)")
        print("4. 自动根据backend_mode推断backend_type")
        
    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())