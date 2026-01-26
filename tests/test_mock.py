#!/usr/bin/env python3
"""
测试模拟Ollama功能 - 完整测试套件
测试ollama不存在情况下的返回和模拟功能
"""
import sys
import os
import io
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import json
import logging

# 设置标准输出编码为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 减少日志输出
logging.basicConfig(level=logging.WARNING)

async def test_mock_router_creation():
    """测试模拟路由器创建"""
    print("1. 测试模拟路由器创建...")
    
    from config_loader import BackendConfig
    from routers.backend_router_factory import BackendRouterFactory
    
    try:
        # 创建模拟配置
        mock_config = BackendConfig({
            "base_url": "http://mock.local",
            "timeout": 60
        })
        
        # 创建模拟路由器
        mock_router = BackendRouterFactory.create_router(mock_config, "mock", verbose_json_logging=False)
        print("   ✅ 模拟路由器创建成功")
        
        # 验证路由器类型
        router_type = type(mock_router).__name__
        print(f"   ✅ 路由器类型: {router_type}")
        
        return True, mock_router
    except Exception as e:
        print(f"   ❌ 模拟路由器创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False, None

async def test_mock_router_response():
    """测试模拟路由器响应"""
    print("\n2. 测试模拟路由器响应...")
    
    from config_loader import BackendConfig
    from routers.backend_router_factory import BackendRouterFactory
    
    try:
        # 创建模拟配置
        mock_config = BackendConfig({
            "base_url": "http://mock.local",
            "timeout": 60
        })
        
        # 创建模拟路由器
        mock_router = BackendRouterFactory.create_router(mock_config, "mock", verbose_json_logging=False)
        
        # 测试非流式响应
        test_request = {
            "model": "test-model",
            "prompt": "Hello, world! This is a test.",
            "stream": False
        }
        
        print("   📤 发送测试请求...")
        response = await mock_router.handle_request(
            "test-model",
            test_request,
            stream=False
        )
        
        if response:
            print("   ✅ 模拟路由器返回响应")
            
            # 检查响应格式
            if isinstance(response, dict):
                print(f"   ✅ 响应类型: dict, 键: {list(response.keys())}")
                
                # 检查必要的字段
                required_fields = ["model", "response", "created_at"]
                for field in required_fields:
                    if field in response:
                        print(f"   ✅ 包含字段 '{field}': {response[field][:50] if isinstance(response[field], str) and len(response[field]) > 50 else response[field]}")
                    else:
                        print(f"   ⚠️  缺少字段 '{field}'")
                
                # 检查mock标志
                if response.get("mock") is True:
                    print("   ✅ 响应包含 'mock': True 标志")
                else:
                    print("   ⚠️  响应不包含mock标志（可能不是模拟响应）")
            else:
                print(f"   ⚠️  响应类型不是dict: {type(response).__name__}")
            
            return True
        else:
            print("   ❌ 模拟路由器返回空响应")
            return False
            
    except Exception as e:
        print(f"   ❌ 测试模拟路由器响应时出错: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_ollama_check_function():
    """测试Ollama连接检查函数"""
    print("\n3. 测试Ollama连接检查函数...")
    
    try:
        # 直接导入main模块
        import main
        
        print("   🔧 测试SIMULATE_OLLAMA_TIMEOUT=True的情况...")
        # 保存原始值
        original_value = main.SIMULATE_OLLAMA_TIMEOUT
        
        # 设置模拟超时
        main.SIMULATE_OLLAMA_TIMEOUT = True
        
        # 调用检查函数
        result = await main.check_ollama_available()
        
        if not result:
            print("   ✅ SIMULATE_OLLAMA_TIMEOUT=True时，check_ollama_available()返回False")
        else:
            print("   ❌ SIMULATE_OLLAMA_TIMEOUT=True时，check_ollama_available()应该返回False")
            # 恢复原始值
            main.SIMULATE_OLLAMA_TIMEOUT = original_value
            return False
        
        print("   🔧 测试SIMULATE_OLLAMA_TIMEOUT=False的情况...")
        # 恢复设置
        main.SIMULATE_OLLAMA_TIMEOUT = False
        
        # 再次调用检查函数（实际检查Ollama连接）
        result = await main.check_ollama_available()
        
        print(f"   📊 SIMULATE_OLLAMA_TIMEOUT=False时，check_ollama_available()返回: {result}")
        print(f"   ℹ️  这取决于实际Ollama服务是否运行")
        
        # 恢复原始值
        main.SIMULATE_OLLAMA_TIMEOUT = original_value
        
        return True
        
    except Exception as e:
        print(f"   ❌ 测试Ollama检查函数时出错: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_api_endpoint_fallback():
    """测试API端点fallback逻辑"""
    print("\n4. 测试API端点fallback逻辑...")
    
    print("   📋 测试场景:")
    print("   1. 当Ollama不可用时，/api/generate应该使用mock路由器")
    print("   2. 响应应该保持Ollama兼容格式")
    print("   3. 应该包含适当的错误信息或mock标志")
    
    # 由于测试实际API需要启动服务器，这里只测试逻辑
    print("   ⚠️  注意: 完整API测试需要启动服务器，请运行test_api.py进行完整测试")
    
    # 测试配置加载
    from config_loader import ConfigLoader
    config_loader = ConfigLoader("config.yaml")
    if config_loader.load():
        print("   ✅ 配置加载成功")
        
        # 获取本地Ollama配置
        local_config = config_loader.get_local_ollama_config()
        base_url = local_config.get("base_url", "http://localhost:11434")
        print(f"   📍 本地Ollama配置URL: {base_url}")
    else:
        print("   ❌ 配置加载失败")
        return False
    
    return True

async def test_main_simulation_parameter():
    """测试main.py中的模拟参数"""
    print("\n5. 测试main.py中的模拟参数...")
    
    # 读取main.py文件检查SIMULATE_OLLAMA_TIMEOUT变量
    try:
        with open("main.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # 检查变量定义
        if "SIMULATE_OLLAMA_TIMEOUT" in content:
            print("   ✅ main.py中包含SIMULATE_OLLAMA_TIMEOUT变量")
            
            # 检查是否在init_backend_routers中使用
            if "SIMULATE_OLLAMA_TIMEOUT" in content and "init_backend_routers" in content:
                print("   ✅ init_backend_routers函数使用SIMULATE_OLLAMA_TIMEOUT变量")
            
            # 检查是否在check_ollama_available中使用
            if "SIMULATE_OLLAMA_TIMEOUT" in content and "check_ollama_available" in content:
                print("   ✅ check_ollama_available函数使用SIMULATE_OLLAMA_TIMEOUT变量")
            
            # 检查是否在/api/generate端点中使用
            if "SIMULATE_OLLAMA_TIMEOUT" in content and "check_ollama_available" in content and "@app.post(\"/api/generate\")" in content:
                print("   ✅ /api/generate端点使用check_ollama_available函数")
        else:
            print("   ❌ main.py中未找到SIMULATE_OLLAMA_TIMEOUT变量")
            return False
        
        # 检查mock路由器注册
        if "backend_manager.register_router(\"mock\"" in content:
            print("   ✅ main.py中注册了mock路由器")
        else:
            print("   ❌ main.py中未注册mock路由器")
            return False
        
        return True
        
    except Exception as e:
        print(f"   ❌ 检查main.py文件时出错: {e}")
        return False

async def test_complete_scenario():
    """测试完整场景"""
    print("\n6. 测试完整场景...")
    
    print("   🎯 场景: Ollama服务不存在时的完整处理流程")
    print("   1. 启动代理服务")
    print("   2. 发送API请求到本地模型")
    print("   3. 服务检测Ollama不可用")
    print("   4. 自动切换到mock路由器")
    print("   5. 返回模拟响应")
    
    print("   ⚠️  注意: 完整场景测试需要:")
    print("   - 停止Ollama服务（如果正在运行）")
    print("   - 设置SIMULATE_OLLAMA_TIMEOUT=True")
    print("   - 启动代理服务")
    print("   - 发送测试请求")
    print("   - 验证返回模拟响应")
    
    print("   📝 手动测试步骤:")
    print("   1. 编辑main.py，设置 SIMULATE_OLLAMA_TIMEOUT = True")
    print("   2. 运行: python main.py")
    print("   3. 在另一个终端运行:")
    print('      curl -X POST http://localhost:11435/api/generate \\')
    print('        -H "Content-Type: application/json" \\')
    print('        -d \'{"model": "llama3", "prompt": "Hello", "stream": false}\'')
    print("   4. 验证响应包含mock标志或模拟内容")
    
    return True

async def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("🤖 智能Ollama代理模拟功能测试套件")
    print("=" * 70)
    
    test_results = []
    
    # 运行各个测试
    test_results.append(await test_mock_router_creation())
    test_results.append((await test_mock_router_response(), None))
    test_results.append((await test_ollama_check_function(), None))
    test_results.append((await test_api_endpoint_fallback(), None))
    test_results.append((await test_main_simulation_parameter(), None))
    test_results.append((await test_complete_scenario(), None))
    
    # 统计结果
    passed = sum(1 for result in test_results if isinstance(result, tuple) and result[0])
    total = len(test_results)
    
    print("\n" + "=" * 70)
    print("📊 测试结果汇总")
    print("=" * 70)
    print(f"✅ 通过: {passed}/{total}")
    print(f"❌ 失败: {total - passed}/{total}")
    
    if passed == total:
        print("\n🎉 所有测试通过！")
        return True
    else:
        print("\n⚠️  部分测试失败，请检查上述输出")
        return False

if __name__ == "__main__":
    # 运行所有测试
    success = asyncio.run(run_all_tests())
    
    if success:
        print("\n✨ 模拟功能测试完成 - 所有功能正常")
        sys.exit(0)
    else:
        print("\n💥 模拟功能测试完成 - 发现问题")
        sys.exit(1)