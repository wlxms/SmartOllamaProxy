#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试重构后的smart_ollama_proxy
"""
import sys
import os
import io
import asyncio
import logging

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设置UTF-8编码输出（避免文件句柄关闭问题）
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_config_loading():
    """测试配置加载"""
    print("=" * 60)
    print("测试配置加载")
    print("=" * 60)
    
    try:
        from config_loader import ConfigLoader
        
        cl = ConfigLoader("config.yaml")
        success = cl.load()
        
        if success:
            print("✅ 配置加载成功")
            
            # 显示模型组
            model_groups = list(cl.models.keys())
            print(f"📊 模型组: {len(model_groups)} 个")
            for group in model_groups:
                model_config = cl.models[group]
                print(f"  - {group}: {model_config.description}")
                print(f"    可用模型: {len(model_config.available_models)} 个")
                if model_config.available_models:
                    print(f"    示例: {model_config.available_models[:3]}")
            
            # 显示虚拟模型
            virtual_models = cl.get_all_virtual_models()
            print(f"✨ 虚拟模型: {len(virtual_models)} 个")
            print(f"  示例: {list(virtual_models)[:5]}")
            
            # 显示后端配置
            backend_configs = cl.get_all_backend_configs()
            print(f"🔌 后端配置: {len(backend_configs)} 个")
            for name, config in list(backend_configs.items())[:3]:
                print(f"  - {name}")
                print(f"    URL: {config.base_url}")
                print(f"    Timeout: {config.timeout}")
            
            return True
        else:
            print("❌ 配置加载失败")
            return False
            
    except Exception as e:
        print(f"❌ 配置加载测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_backend_routers():
    """测试后端路由器"""
    print("\n" + "=" * 60)
    print("测试后端路由器")
    print("=" * 60)
    
    try:
        from config_loader import ConfigLoader
        from routers.backend_router_factory import BackendRouterFactory, BackendManager
        
        cl = ConfigLoader("config.yaml")
        cl.load()
        
        bm = BackendManager()
        
        # 初始化路由器
        backend_configs = cl.get_all_backend_configs()
        print(f"找到 {len(backend_configs)} 个后端配置")
        
        for name, config in backend_configs.items():
            try:
                router = BackendRouterFactory.create_router(config, verbose_json_logging=False)
                bm.register_router(name, router)
                print(f"✅ 注册路由器: {name}")
            except Exception as e:
                print(f"❌ 注册路由器失败 {name}: {e}")
        
        print(f"📋 总共注册了 {len(bm.routers)} 个路由器")
        
        # 测试本地Ollama路由器
        local_config = cl.get_local_ollama_config()
        from config_loader import BackendConfig as BC
        local_backend_config = BC({
            "base_url": local_config.get("base_url", "http://localhost:11434"),
            "timeout": local_config.get("timeout", 60)
        })
        local_router = BackendRouterFactory.create_router(local_backend_config, "ollama", verbose_json_logging=False)
        bm.register_router("local", local_router)
        print("✅ 注册本地Ollama路由器")
        
        return True
        
    except Exception as e:
        print(f"❌ 后端路由器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_model_routing_async():
    """测试模型路由（异步版本）"""
    print("\n" + "=" * 60)
    print("测试模型路由")
    print("=" * 60)
    
    try:
        from config_loader import ConfigLoader, ModelRouter
        
        cl = ConfigLoader("config.yaml")
        cl.load()
        
        model_router = ModelRouter(cl)
        
        # 测试一些模型路由
        test_models = [
            "deepseek-chat",      # 应该路由到DeepSeek
            "gpt-4o",            # 应该路由到OpenAI
            "claude-3-5-sonnet", # 应该路由到Claude
            "llama-3.3-70b",     # 应该路由到Groq
            "unknown-model",     # 应该路由到本地
        ]
        
        for model in test_models:
            try:
                backend_infos = await model_router.route_request(model)
                if backend_infos is None:
                    print(f"  {model}: ➡️ 路由到本地Ollama")
                else:
                    # 可能有多个后端，取第一个显示
                    backend_config, actual_model = backend_infos[0]
                    print(f"  {model}: ➡️ 路由到 {backend_config.base_url} (实际模型: {actual_model}) (共 {len(backend_infos)} 个后端)")
            except Exception as e:
                print(f"  {model}: ❌ 路由失败: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 模型路由测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_model_routing():
    """包装异步测试"""
    import asyncio
    return asyncio.run(test_model_routing_async())

def test_main_app():
    """测试主应用"""
    print("\n" + "=" * 60)
    print("测试主应用")
    print("=" * 60)
    
    try:
        # 测试FastAPI应用创建
        from main import app
        
        print("✅ FastAPI应用创建成功")
        print(f"📋 应用标题: {app.title}")
        
        # 检查端点 - 使用兼容方式
        routes = []
        for route in app.routes:
            # 获取路径
            path = getattr(route, 'path', None)
            if path is None:
                continue
                
            # 获取方法
            methods = []
            if hasattr(route, 'methods'):
                methods = list(getattr(route, 'methods', []))
            elif hasattr(route, 'endpoint'):
                # 对于APIRoute
                pass
                
            method_str = ','.join(methods) if methods else 'ANY'
            routes.append(f"{method_str} {path}")
        
        print(f"🔗 注册了 {len(routes)} 个端点")
        print("  主要端点:")
        for route in sorted(routes)[:10]:  # 显示前10个
            print(f"    - {route}")
        
        return True
        
    except Exception as e:
        print(f"❌ 主应用测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("🤖 Smart Ollama Proxy 重构测试")
    print("=" * 60)
    
    tests = [
        ("配置加载", test_config_loading),
        ("后端路由器", test_backend_routers),
        ("模型路由", test_model_routing),
        ("主应用", test_main_app),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n▶️ 运行测试: {test_name}")
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"❌ 测试异常: {e}")
            results.append((test_name, False))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    all_passed = True
    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{test_name}: {status}")
        if not success:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试通过！重构成功。")
        print("\n下一步:")
        print("1. 更新配置文件中的API密钥")
        print("2. 运行: python main.py")
        print("3. 在Copilot中配置Ollama地址为: http://localhost:11435")
    else:
        print("⚠️  部分测试失败，需要检查问题。")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)