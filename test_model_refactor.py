#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试重构后的模型选择机制
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import ConfigLoader
import asyncio

async def test_model_refactor():
    """测试重构后的模型选择机制"""
    print("测试重构后的模型选择机制")
    print("=" * 60)
    
    # 加载配置
    config_loader = ConfigLoader("config.yaml")
    if not config_loader.load():
        print("配置加载失败")
        return False
    
    print(f"配置加载成功，加载了 {len(config_loader.models)} 个模型组")
    
    # 测试各种模型名格式
    test_cases = [
        # (模型名, 期望的组名, 期望的模型名)
        ("deepseek-chat", "deepseek", "deepseek-chat"),
        ("deepseek/deepseek-chat", "deepseek", "deepseek-chat"),
        ("deepseek-reasoner", "deepseek", "deepseek-reasoner"),
        ("deepseek/deepseek-reasoner", "deepseek", "deepseek-reasoner"),
        ("qwen3-max", "qwen", "qwen3-max"),
        ("qwen/qwen3-max", "qwen", "qwen3-max"),
        ("llama3:latest", "local", "llama3:latest"),  # 本地模型
    ]
    
    print("\n测试模型配置查找:")
    all_passed = True
    
    for model_name, expected_group, expected_inner_model in test_cases:
        result = config_loader.get_model_config(model_name)
        if result:
            model_config, inner_model = result
            group_name = model_config.model_group
            passed = (group_name == expected_group and inner_model == expected_inner_model)
            status = "PASS" if passed else "FAIL"
            print(f"{status:5} {model_name:30} -> 组: {group_name:15}, 模型: {inner_model:20} (期望: {expected_group}/{expected_inner_model})")
            if not passed:
                all_passed = False
        else:
            print(f"FAIL {model_name:30} -> 未找到配置")
            all_passed = False
    
    # 测试模型列表
    print("\n测试模型列表生成:")
    try:
        from config_loader import ModelRouter
        model_router = ModelRouter(config_loader)
        combined_models = await model_router.get_combined_models()
        
        # 检查虚拟模型是否包含组名前缀
        virtual_models_with_group = [m for m in combined_models if m.get("details", {}).get("format") == "api"]
        print(f"找到 {len(virtual_models_with_group)} 个虚拟模型")
        
        # 检查前几个虚拟模型的名称格式
        for model in virtual_models_with_group[:3]:
            model_name = model.get("name", "")
            model_field = model.get("model", "")
            print(f"   - {model_name} (model字段: {model_field})")
            if '/' in model_name:
                print(f"     包含组名前缀 - PASS")
            else:
                print(f"     不包含组名前缀 - WARNING")
    except Exception as e:
        print(f"模型列表测试失败: {e}")
        all_passed = False
    
    # 测试后端配置查找
    print("\n测试后端配置查找:")
    test_backend_cases = [
        "deepseek-chat",
        "deepseek/deepseek-chat",
        "qwen3-max",
        "qwen/qwen3-max",
    ]
    
    for model_name in test_backend_cases:
        backends = config_loader.get_backends_for_model(model_name)
        if backends:
            print(f"PASS {model_name:30} -> 找到 {len(backends)} 个后端配置")
            for i, (backend, actual_model) in enumerate(backends):
                print(f"     {i+1}. 后端模式: {backend.backend_mode}, 实际模型: {actual_model}")
        else:
            print(f"FAIL {model_name:30} -> 未找到后端配置")
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("所有测试通过!")
        return True
    else:
        print("部分测试失败")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_model_refactor())
    sys.exit(0 if success else 1)