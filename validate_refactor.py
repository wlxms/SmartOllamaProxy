#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证重构后的功能，确保所有API端点正常工作
"""
import sys
import os
import json
import asyncio
from typing import Dict, Any
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import ConfigLoader
from config_loader import ModelRouter
from main import app, show_model
from fastapi.testclient import TestClient

async def validate_refactored_features():
    """验证重构后的功能"""
    print("验证重构后的功能")
    print("=" * 60)
    
    # 加载配置
    config_loader = ConfigLoader("config.yaml")
    if not config_loader.load():
        print("配置加载失败")
        return False
    
    print(f"配置加载成功，加载了 {len(config_loader.models)} 个模型组")
    
    # 1. 测试模型列表生成
    print("\n1. 测试模型列表生成:")
    model_router = ModelRouter(config_loader)
    combined_models = await model_router.get_combined_models()
    
    # 检查虚拟模型是否包含组名前缀
    virtual_models = [m for m in combined_models if m.get("details", {}).get("format") == "api"]
    print(f"  找到 {len(virtual_models)} 个虚拟模型")
    
    all_virtual_have_prefix = True
    for model in virtual_models:
        model_name = model.get("name", "")
        if '/' not in model_name:
            print(f"  警告: 虚拟模型 {model_name} 不包含组名前缀")
            all_virtual_have_prefix = False
    
    if all_virtual_have_prefix:
        print("  ✅ 所有虚拟模型都包含组名前缀")
    else:
        print("  ❌ 部分虚拟模型不包含组名前缀")
    
    # 2. 测试模型配置查找（带组名和不带组名）
    print("\n2. 测试模型配置查找:")
    test_cases = [
        ("deepseek-chat", "deepseek", "deepseek-chat"),
        ("deepseek/deepseek-chat", "deepseek", "deepseek-chat"),
        ("deepseek-reasoner", "deepseek", "deepseek-reasoner"),
        ("deepseek/deepseek-reasoner", "deepseek", "deepseek-reasoner"),
        ("qwen3-max", "qwen", "qwen3-max"),
        ("qwen/qwen3-max", "qwen", "qwen3-max"),
    ]
    
    all_config_tests_passed = True
    for model_name, expected_group, expected_inner_model in test_cases:
        result = config_loader.get_model_config(model_name)
        if result:
            model_config, inner_model = result
            if model_config.model_group == expected_group and inner_model == expected_inner_model:
                print(f"  ✅ {model_name:30} -> {model_config.model_group}/{inner_model}")
            else:
                print(f"  ❌ {model_name:30} -> {model_config.model_group}/{inner_model} (期望: {expected_group}/{expected_inner_model})")
                all_config_tests_passed = False
        else:
            print(f"  ❌ {model_name:30} -> 未找到配置")
            all_config_tests_passed = False
    
    # 3. 测试后端配置查找
    print("\n3. 测试后端配置查找:")
    backend_test_cases = [
        "deepseek-chat",
        "deepseek/deepseek-chat",
        "deepseek-reasoner",
        "deepseek/deepseek-reasoner",
    ]
    
    all_backend_tests_passed = True
    for model_name in backend_test_cases:
        backends = config_loader.get_backends_for_model(model_name)
        if backends:
            print(f"  ✅ {model_name:30} -> 找到 {len(backends)} 个后端配置")
            for i, (backend, actual_model) in enumerate(backends):
                print(f"      {i+1}. 后端模式: {backend.backend_mode}, 实际模型: {actual_model}")
        else:
            print(f"  ❌ {model_name:30} -> 未找到后端配置")
            all_backend_tests_passed = False
    
    # 4. 测试路由功能
    print("\n4. 测试路由功能:")
    routing_test_cases = [
        "deepseek-chat",
        "deepseek/deepseek-chat",
        "qwen3-max",
        "qwen/qwen3-max",
    ]
    
    all_routing_tests_passed = True
    for model_name in routing_test_cases:
        backends = await model_router.route_request(model_name)
        if backends:
            print(f"  ✅ {model_name:30} -> 路由成功，找到 {len(backends)} 个后端")
            for i, (backend, actual_model) in enumerate(backends):
                print(f"      {i+1}. 后端模式: {backend.backend_mode}, 实际模型: {actual_model}")
        else:
            # 可能是本地模型
            if "local" in model_name or model_name.endswith(":latest"):
                print(f"  ⚠️  {model_name:30} -> 路由到本地模型")
            else:
                print(f"  ❌ {model_name:30} -> 路由失败")
                all_routing_tests_passed = False
    
    # 5. 使用TestClient测试API端点
    print("\n5. 使用TestClient测试API端点:")
    try:
        client = TestClient(app)
        
        # 测试根端点
        response = client.get("/")
        if response.status_code == 200:
            print(f"  ✅ GET / -> 状态码: {response.status_code}")
            data = response.json()
            print(f"     消息: {data.get('message', 'N/A')}")
        else:
            print(f"  ❌ GET / -> 状态码: {response.status_code}")
            all_config_tests_passed = False
        
        # 测试模型列表端点
        response = client.get("/api/tags")
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            print(f"  ✅ GET /api/tags -> 状态码: {response.status_code}, 模型数: {len(models)}")
            
            # 检查是否有带组名的模型
            models_with_prefix = [m for m in models if '/' in m.get("name", "")]
            print(f"     包含组名前缀的模型: {len(models_with_prefix)} 个")
            
            # 显示几个示例
            for model in models_with_prefix[:3]:
                print(f"     - {model.get('name', 'N/A')}")
        else:
            print(f"  ❌ GET /api/tags -> 状态码: {response.status_code}")
            all_config_tests_passed = False
            
    except Exception as e:
        print(f"  ❌ TestClient测试失败: {e}")
        all_config_tests_passed = False
    
    # 总结
    print("\n" + "=" * 60)
    print("验证结果:")
    print(f"  模型列表生成: {'✅' if all_virtual_have_prefix else '❌'}")
    print(f"  模型配置查找: {'✅' if all_config_tests_passed else '❌'}")
    print(f"  后端配置查找: {'✅' if all_backend_tests_passed else '❌'}")
    print(f"  路由功能: {'✅' if all_routing_tests_passed else '❌'}")
    
    all_passed = (all_virtual_have_prefix and all_config_tests_passed and 
                  all_backend_tests_passed and all_routing_tests_passed)
    
    if all_passed:
        print("\n🎉 所有验证通过!")
        return True
    else:
        print("\n❌ 部分验证失败")
        return False

if __name__ == "__main__":
    success = asyncio.run(validate_refactored_features())
    sys.exit(0 if success else 1)