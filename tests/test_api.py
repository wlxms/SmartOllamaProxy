#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API测试脚本 - 测试重构后的smart_ollama_proxy API端点
"""
import sys
import os
import io
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import json
import logging
from typing import Dict, Any

# 设置UTF-8编码输出（避免文件句柄关闭问题）
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 减少日志输出
logging.basicConfig(level=logging.WARNING)

async def test_api_endpoints():
    """测试API端点"""
    print("🤖 Smart Ollama Proxy API 测试")
    print("=" * 60)
    
    # 在函数开头声明变量
    server = None
    server_task = None
    
    try:
        import httpx
        from main import app
        import uvicorn
        import asyncio
        
        # 获取配置
        from config_loader import ConfigLoader
        config_loader = ConfigLoader("config.yaml")
        config_loader.load()
        proxy_config = config_loader.get_proxy_config()
        port = proxy_config.get("port", 11435)
        host = proxy_config.get("host", "0.0.0.0")
        
        # 使用localhost进行测试，避免0.0.0.0的连接问题
        test_host = "127.0.0.1" if host == "0.0.0.0" else host
        base_url = f"http://{test_host}:{port}"
        
        print(f"📡 测试服务器: {base_url}")
        print(f"🚀 正在启动服务器 (绑定到 {host}:{port})...")
        
        # 创建服务器配置
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="warning",  # 减少日志输出
            access_log=False
        )
        
        server = uvicorn.Server(config)
        
        # 在后台启动服务器
        server_task = asyncio.create_task(server.serve())
        
        # 等待服务器启动
        print("⏳ 等待服务器启动...")
        
        # 尝试多次连接，确保服务器已启动
        max_attempts = 10
        server_started = False
        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(f"{base_url}/")
                    if response.status_code == 200:
                        print(f"✅ 服务器已启动 (尝试 {attempt + 1}/{max_attempts})")
                        server_started = True
                        break
            except Exception as conn_error:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(1)
                else:
                    print(f"⚠️  服务器可能未正确启动: {conn_error}")
        
        if not server_started:
            print("❌ 服务器启动失败，跳过API测试")
            # 停止服务器
            if server is not None:
                server.should_exit = True
            if server_task is not None:
                await server_task
            return False
        
        print("开始测试...")
        print()
        
        # 测试根端点
        print("1. 测试根端点 (GET /)")
        print("-" * 40)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/")
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ 状态码: {response.status_code}")
                    print(f"📋 消息: {data.get('message')}")
                    print(f"🔢 版本: {data.get('version')}")
                    print(f"🏗️  架构: {data.get('architecture')}")
                    
                    # 显示端点
                    endpoints = data.get('endpoints', {})
                    print(f"🔗 可用端点: {len(endpoints)} 个")
                    for endpoint, desc in endpoints.items():
                        print(f"   - {endpoint}: {desc}")
                else:
                    print(f"❌ 状态码: {response.status_code}")
                    print(f"📄 响应: {response.text}")
        except Exception as e:
            print(f"❌ 请求失败: {e}")
        
        print()
        
        # 测试模型列表端点
        print("2. 测试模型列表 (GET /api/tags)")
        print("-" * 40)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = data.get('models', [])
                    print(f"✅ 状态码: {response.status_code}")
                    print(f"📊 模型数量: {len(models)} 个")
                    
                    # 显示模型类型
                    local_models = []
                    virtual_models = []
                    
                    for model in models:
                        name = model.get('name', '')
                        details = model.get('details', {})
                        format_type = details.get('format', '')
                        
                        if format_type == 'api':
                            virtual_models.append(name)
                        else:
                            local_models.append(name)
                    
                    print(f"🏠 本地模型: {len(local_models)} 个")
                    if local_models:
                        print(f"   示例: {local_models[:3]}")
                    
                    print(f"✨ 虚拟模型: {len(virtual_models)} 个")
                    if virtual_models:
                        print(f"   示例: {virtual_models[:5]}")
                else:
                    print(f"❌ 状态码: {response.status_code}")
                    print(f"📄 响应: {response.text}")
        except Exception as e:
            print(f"❌ 请求失败: {e}")
        
        print()
        
        # 测试版本端点
        print("3. 测试版本信息 (GET /api/version)")
        print("-" * 40)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/api/version")
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ 状态码: {response.status_code}")
                    print(f"🔢 版本: {data.get('version')}")
                else:
                    print(f"❌ 状态码: {response.status_code}")
                    print(f"📄 响应: {response.text}")
        except Exception as e:
            print(f"❌ 请求失败: {e}")
        
        print()
        
        # 测试模型信息端点（模拟请求）
        print("4. 测试模型信息 (POST /api/show)")
        print("-" * 40)
        print("📝 注意: 此测试发送模拟请求")
        
        # 测试虚拟模型和本地模型
        test_models = ["deepseek-chat", "qwen3-coder:480b-cloud"]
        for model_name in test_models:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    request_data = {"model": model_name}
                    response = await client.post(
                        f"{base_url}/api/show",
                        json=request_data
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        print(f"✅ {model_name}: 获取成功")
                        details = data.get('details', {})
                        print(f"   格式: {details.get('format', 'unknown')}")
                        print(f"   家族: {details.get('family', 'unknown')}")
                    else:
                        print(f"⚠️  {model_name}: 状态码 {response.status_code}")
            except Exception as e:
                print(f"❌ {model_name}: 请求失败 - {e}")
        
        print()
        
        # 测试生成端点（模拟请求）
        print("5. 测试生成请求 (POST /api/generate)")
        print("-" * 40)
        print("📝 注意: 此测试发送模拟请求到本地模型")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 测试本地模型请求 - 使用实际可用的本地模型
                request_data = {
                    "model": "qwen3-coder:480b-cloud",  # 使用实际可用的本地模型
                    "prompt": "Hello, please respond with 'TEST OK' only.",
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 10
                    }
                }
                
                print(f"📤 发送请求到: {request_data['model']}")
                print(f"📝 提示: {request_data['prompt']}")
                
                response = await client.post(
                    f"{base_url}/api/generate",
                    json=request_data,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ 状态码: {response.status_code}")
                    print(f"📋 模型: {data.get('model')}")
                    print(f"📄 响应: {data.get('response', '')[:100]}...")
                    print(f"✅ 完成: {data.get('done', False)}")
                elif response.status_code == 404:
                    print(f"⚠️  状态码: {response.status_code} - 模型未找到")
                    print("   这可能是正常的，如果本地没有llama2模型")
                else:
                    print(f"❌ 状态码: {response.status_code}")
                    print(f"📄 响应: {response.text[:200]}")
        except httpx.TimeoutException:
            print("⏰ 请求超时 - 可能是本地Ollama未运行")
        except Exception as e:
            print(f"❌ 请求失败: {e}")
        
        print()
        
        # 测试OpenAI兼容端点（模拟请求）
        print("6. 测试OpenAI兼容端点 (POST /v1/chat/completions)")
        print("-" * 40)
        print("📝 注意: 此测试发送模拟请求")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                request_data = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "user", "content": "Hello, please respond with 'TEST OK' only."}
                    ],
                    "stream": False,
                    "temperature": 0.1,
                    "max_tokens": 10
                }
                
                print(f"📤 发送请求到: {request_data['model']}")
                
                response = await client.post(
                    f"{base_url}/v1/chat/completions",
                    json=request_data,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ 状态码: {response.status_code}")
                    print(f"📋 模型: {data.get('model')}")
                    
                    choices = data.get('choices', [])
                    if choices:
                        message = choices[0].get('message', {})
                        print(f"📄 响应: {message.get('content', '')[:100]}...")
                elif response.status_code == 404:
                    print(f"⚠️  状态码: {response.status_code} - 端点未找到")
                elif response.status_code == 500:
                    print(f"⚠️  状态码: {response.status_code} - 服务器错误")
                    print("   这可能是正常的，如果API密钥未配置")
                else:
                    print(f"❌ 状态码: {response.status_code}")
                    print(f"📄 响应: {response.text[:200]}")
        except httpx.TimeoutException:
            print("⏰ 请求超时")
        except Exception as e:
            print(f"❌ 请求失败: {e}")
        
        print()
        print("=" * 60)
        print("🎉 API测试完成")
        print()
        print("🛑 正在停止服务器...")
        
        # 停止服务器
        server.should_exit = True
        await server_task
        
        print("✅ 服务器已停止")
        print()
        print("📋 总结:")
        print("  1. 测试已完成，服务器已自动关闭")
        print("  2. 配置正确的API密钥以测试云端模型")
        print("  3. 确保本地Ollama运行以测试本地模型")
        print("  4. 查看日志获取详细错误信息")
        
        return True
        
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        print("请确保已安装所有依赖:")
        print("  pip install fastapi uvicorn httpx pydantic pyyaml")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 确保服务器被停止
        try:
            if server is not None:
                server.should_exit = True
            if server_task is not None:
                await server_task
        except Exception as stop_error:
            print(f"⚠️  停止服务器时出错: {stop_error}")
            
        return False

def main():
    """主函数"""
    # 运行异步测试
    try:
        success = asyncio.run(test_api_endpoints())
        return success
    except RuntimeError:
        # 如果已经在事件循环中，使用嵌套方式
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(test_api_endpoints())
        loop.close()
        return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)