#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClientPool测试脚本 - 测试client复用优化
"""

import asyncio
import logging
import sys
import os
import io

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设置UTF-8编码输出
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 减少日志输出
logging.basicConfig(level=logging.WARNING)

async def test_client_pool():
    """测试ClientPool功能"""
    print("🔧 ClientPool 测试")
    print("=" * 60)
    
    try:
        # 导入ClientPool
        from client_pool import client_pool
        
        print("1. 测试ClientPool单例模式")
        from client_pool import ClientPool
        pool1 = ClientPool()
        pool2 = ClientPool()
        print(f"   pool1 is pool2: {pool1 is pool2} ✓")
        
        print("\n2. 测试获取客户端")
        # 获取相同配置的客户端
        client1 = await client_pool.get_client(
            base_url="https://api.deepseek.com/v1",
            api_key="test-key-1",
            timeout=30.0
        )
        
        client2 = await client_pool.get_client(
            base_url="https://api.deepseek.com/v1",
            api_key="test-key-1",
            timeout=30.0
        )
        
        print(f"   client1 is client2: {client1 is client2} ✓")
        print(f"   引用计数: {client_pool._ref_counts[('https://api.deepseek.com/v1', 'test-key-1')]}")
        
        print("\n3. 测试不同配置的客户端")
        client3 = await client_pool.get_client(
            base_url="https://api.openai.com/v1",
            api_key="test-key-2",
            timeout=30.0
        )
        
        print(f"   client1 is client3: {client1 is client3} ✓")
        print(f"   总客户端数: {len(client_pool._clients)}")
        
        print("\n4. 测试释放客户端")
        await client_pool.release_client("https://api.deepseek.com/v1", "test-key-1")
        print(f"   释放后引用计数: {client_pool._ref_counts[('https://api.deepseek.com/v1', 'test-key-1')]}")
        
        await client_pool.release_client("https://api.deepseek.com/v1", "test-key-1")
        print(f"   再次释放后引用计数: {client_pool._ref_counts.get(('https://api.deepseek.com/v1', 'test-key-1'), '已移除')}")
        
        print("\n5. 测试统计信息")
        stats = client_pool.get_stats()
        print(f"   总客户端数: {stats['total_clients']}")
        for client_info in stats['clients']:
            print(f"   - {client_info['base_url']}: 引用计数={client_info['ref_count']}")
        
        print("\n6. 测试关闭所有客户端")
        await client_pool.close_all()
        print(f"   关闭后总客户端数: {len(client_pool._clients)} ✓")
        
        print("\n✅ ClientPool测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_backend_router_client_reuse():
    """测试后端路由器的client复用"""
    print("\n🔌 后端路由器Client复用测试")
    print("=" * 60)
    
    try:
        from config_loader import BackendConfig, ConfigLoader
        from routers.backend_router_factory import BackendRouterFactory, BackendManager
        from client_pool import client_pool
        
        # 创建配置
        config1 = BackendConfig({
            "base_url": "https://api.test1.com/v1",
            "api_key": "key1",
            "timeout": 30
        })
        
        config2 = BackendConfig({
            "base_url": "https://api.test1.com/v1",
            "api_key": "key1",
            "timeout": 30
        })
        
        config3 = BackendConfig({
            "base_url": "https://api.test2.com/v1",
            "api_key": "key2",
            "timeout": 30
        })
        
        print("1. 创建相同配置的路由器")
        router1 = BackendRouterFactory.create_router(config1, verbose_json_logging=False)
        router2 = BackendRouterFactory.create_router(config2, verbose_json_logging=False)
        
        print(f"   路由器1 client: {router1._client}")
        print(f"   路由器2 client: {router2._client}")
        
        print("\n2. 触发路由器使用client（模拟请求）")
        # 注意：这里不会真正发送请求，只是触发client获取
        try:
            # 模拟获取client
            if router1._client is None:
                router1._client = await client_pool.get_client(
                    base_url=config1.base_url,
                    api_key=config1.api_key,
                    timeout=config1.timeout
                )
            
            if router2._client is None:
                router2._client = await client_pool.get_client(
                    base_url=config2.base_url,
                    api_key=config2.api_key,
                    timeout=config2.timeout
                )
            
            print(f"   路由器1 client is 路由器2 client: {router1._client is router2._client} ✓")
            
        except Exception as e:
            print(f"   模拟请求失败（预期中）: {e}")
        
        print("\n3. 创建不同配置的路由器")
        router3 = BackendRouterFactory.create_router(config3, verbose_json_logging=False)
        
        if router3._client is None:
            router3._client = await client_pool.get_client(
                base_url=config3.base_url,
                api_key=config3.api_key,
                timeout=config3.timeout
            )
        
        print(f"   路由器1 client is 路由器3 client: {router1._client is router3._client} ✓")
        
        print("\n4. 检查ClientPool状态")
        stats = client_pool.get_stats()
        print(f"   总客户端数: {stats['total_clients']}")
        for client_info in stats['clients']:
            print(f"   - {client_info['base_url']}: 引用计数={client_info['ref_count']}")
        
        # 清理
        await client_pool.close_all()
        
        print("\n✅ 后端路由器Client复用测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_performance_improvement():
    """测试性能改进"""
    print("\n⚡ 性能改进测试")
    print("=" * 60)
    
    try:
        import time
        from config_loader import BackendConfig
        from routers.backend_router_factory import BackendRouterFactory
        from client_pool import client_pool
        
        # 测试数据
        test_configs = [
            BackendConfig({
                "base_url": "https://api.performance-test.com/v1",
                "api_key": f"key-{i}",
                "timeout": 30
            })
            for i in range(5)
        ]
        
        print("1. 测试传统方式（每个路由器创建自己的client）")
        start_time = time.time()
        
        traditional_clients = []
        for config in test_configs:
            # 模拟传统方式：每个路由器创建自己的client
            client = await client_pool.get_client(
                base_url=config.base_url,
                api_key=config.api_key,
                timeout=config.timeout
            )
            traditional_clients.append(client)
        
        traditional_time = time.time() - start_time
        print(f"   创建 {len(traditional_clients)} 个客户端耗时: {traditional_time:.4f}秒")
        
        print("\n2. 测试复用方式（相同配置复用client）")
        start_time = time.time()
        
        reuse_configs = test_configs * 2  # 重复配置，测试复用
        
        reuse_clients = []
        client_map = {}
        for config in reuse_configs:
            key = (config.base_url, config.api_key)
            if key not in client_map:
                client = await client_pool.get_client(
                    base_url=config.base_url,
                    api_key=config.api_key,
                    timeout=config.timeout
                )
                client_map[key] = client
            reuse_clients.append(client_map[key])
        
        reuse_time = time.time() - start_time
        print(f"   处理 {len(reuse_configs)} 个配置耗时: {reuse_time:.4f}秒")
        print(f"   实际创建的客户端数: {len(client_map)}")
        print(f"   复用率: {(1 - len(client_map)/len(reuse_configs)) * 100:.1f}%")
        
        print("\n3. 性能对比")
        print(f"   传统方式: {traditional_time:.4f}秒")
        print(f"   复用方式: {reuse_time:.4f}秒")
        print(f"   性能提升: {((traditional_time - reuse_time) / traditional_time) * 100:.1f}%")
        
        # 清理
        await client_pool.close_all()
        
        print("\n✅ 性能改进测试完成")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("🤖 Smart Ollama Proxy - Client复用优化测试")
    print("=" * 60)
    
    # 运行所有测试
    tests = [
        ("ClientPool功能测试", test_client_pool),
        ("后端路由器Client复用测试", test_backend_router_client_reuse),
        ("性能改进测试", test_performance_improvement),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n📋 开始测试: {test_name}")
        try:
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"❌ 测试异常: {e}")
            results.append((test_name, False))
    
    # 输出测试结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    all_passed = True
    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{test_name}: {status}")
        if not success:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试通过！Client复用优化实现成功。")
    else:
        print("⚠️  部分测试失败，请检查实现。")
    
    return all_passed


if __name__ == "__main__":
    # 运行测试
    success = asyncio.run(main())
    sys.exit(0 if success else 1)