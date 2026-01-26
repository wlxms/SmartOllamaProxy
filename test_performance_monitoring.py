#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
性能监控测试脚本
测试新增的性能监控点是否正常工作
"""

import asyncio
import httpx
import json
import sys
from typing import Dict, Any


class PerformanceMonitorTest:
    """性能监控测试类"""

    def __init__(self, base_url: str = "http://localhost:11435"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=60.0)

    async def test_streaming_request(self):
        """测试流式请求的性能监控"""
        print("=" * 80)
        print("测试流式请求的性能监控")
        print("=" * 80)

        request_data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "用一句话介绍Python"}
            ],
            "stream": True
        }

        print(f"\n发送流式请求到 {self.base_url}/v1/chat/completions")
        print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}\n")

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=request_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                print(f"响应状态码: {response.status_code}")

                content_lines = []
                async for line in response.aiter_lines():
                    if line.strip():
                        if line.startswith("data: "):
                            data_str = line[6:]  # 去掉 "data: " 前缀
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        content_lines.append(content)
                                        print(content, end="", flush=True)
                            except json.JSONDecodeError:
                                pass

                print("\n\n流式响应接收完成")

                # 检查是否接收到内容
                if content_lines:
                    print(f"✅ 接收到 {len(content_lines)} 个内容块")
                else:
                    print("⚠️  未接收到内容块")

                print("\n预期看到的性能监控日志:")
                print("- [OPENAI /v1/chat/completions] 转发前耗时: X.XXX秒")
                print("- [OPENAI /v1/chat/completions] 开始转发到后端")
                print("- [OpenAIBackendRouter] 首块响应时间: X.XXX秒")
                print("- [OpenAIBackendRouter] 首块到全部块接收耗时: X.XXX秒")
                print("- [OPENAI /v1/chat/completions] 后端转发耗时: X.XXX秒")
                print("- [OPENAI /v1/chat/completions] 总耗时: X.XXX秒")

        except httpx.ConnectError as e:
            print(f"❌ 连接失败: {e}")
            print("请确保代理服务正在运行: python main.py")
            return False
        except httpx.TimeoutException as e:
            print(f"❌ 请求超时: {e}")
            return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False

        return True

    async def test_non_streaming_request(self):
        """测试非流式请求的性能监控"""
        print("\n" + "=" * 80)
        print("测试非流式请求的性能监控")
        print("=" * 80)

        request_data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": "1+1=?"}
            ],
            "stream": False
        }

        print(f"\n发送非流式请求到 {self.base_url}/v1/chat/completions")
        print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}\n")

        try:
            response = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json=request_data,
                headers={"Content-Type": "application/json"}
            )

            print(f"响应状态码: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print("✅ 请求成功")

                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"]["content"]
                    print(f"响应内容: {content}")

                print("\n预期看到的性能监控日志:")
                print("- [OPENAI /v1/chat/completions] 转发前耗时: X.XXX秒")
                print("- [OPENAI /v1/chat/completions] 开始转发到后端")
                print("- [OPENAI /v1/chat/completions] 后端转发耗时: X.XXX秒")
                print("- [OPENAI /v1/chat/completions] 总耗时: X.XXX秒")
            else:
                print(f"❌ 请求失败: {response.text}")
                return False

        except httpx.ConnectError as e:
            print(f"❌ 连接失败: {e}")
            print("请确保代理服务正在运行: python main.py")
            return False
        except httpx.TimeoutException as e:
            print(f"❌ 请求超时: {e}")
            return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False

        return True

    async def test_generate_endpoint(self):
        """测试Ollama /api/generate端点的性能监控"""
        print("\n" + "=" * 80)
        print("测试 /api/generate 端点的性能监控")
        print("=" * 80)

        request_data = {
            "model": "llama3.2:latest",
            "prompt": "Hello",
            "stream": True
        }

        print(f"\n发送流式请求到 {self.base_url}/api/generate")
        print(f"请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}\n")

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=request_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                print(f"响应状态码: {response.status_code}")

                chunk_count = 0
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            if "response" in data:
                                chunk_count += 1
                                print(data["response"], end="", flush=True)
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            pass

                print("\n\n流式响应接收完成")

                if chunk_count > 0:
                    print(f"✅ 接收到 {chunk_count} 个数据块")
                else:
                    print("⚠️  未接收到数据块")

                print("\n预期看到的性能监控日志:")
                print("- [OLLAMA /api/generate] 收到流式请求，模型: llama3.2:latest")
                print("- [OllamaBackendRouter] 连接建立耗时: X.XXX秒")
                print("- [OllamaBackendRouter] 首块响应时间: X.XXX秒")
                print("- [OllamaBackendRouter] 首块到全部块接收耗时: X.XXX秒")
                print("- [OllamaBackendRouter] 流式请求完成，总耗时: X.XXX秒")
                print("- [OLLAMA /api/generate] 总耗时: X.XXX秒")

        except httpx.ConnectError as e:
            print(f"❌ 连接失败: {e}")
            print("请确保代理服务正在运行: python main.py")
            return False
        except httpx.TimeoutException as e:
            print(f"❌ 请求超时: {e}")
            return False
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            return False

        return True

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


async def main():
    """主函数"""
    print("\n" + "🚀" * 40)
    print("Smart Ollama Proxy - 性能监控测试")
    print("🚀" * 40 + "\n")

    tester = PerformanceMonitorTest()

    try:
        # 测试1: 流式请求
        result1 = await tester.test_streaming_request()
        if not result1:
            print("\n⚠️  流式请求测试失败，跳过其他测试")
            return

        # 等待一下
        await asyncio.sleep(1)

        # 测试2: 非流式请求
        result2 = await tester.test_non_streaming_request()
        if not result2:
            print("\n⚠️  非流式请求测试失败")

        # 等待一下
        await asyncio.sleep(1)

        # 测试3: Ollama generate端点
        result3 = await tester.test_generate_endpoint()
        if not result3:
            print("\n⚠️  /api/generate 测试失败")

        print("\n" + "=" * 80)
        print("✅ 所有测试完成！")
        print("=" * 80)
        print("\n请查看代理服务日志，确认所有性能监控指标是否正确输出。")
        print("\n日志文件位置: logs/ 目录下")

    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
