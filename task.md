[2026-01-27T18:27:45.928993] INFO: smart_ollama_proxy - INFO - 模型 qwen-coder/qwen3-coder-plus 的路由结果: 1 个后端配置
[2026-01-27T18:27:45.929058] INFO: smart_ollama_proxy - INFO - 模型 qwen-coder/qwen3-coder-plus 的候选路由器: ['qwen-coder.openai_backend']
[2026-01-27T18:27:45.929088] INFO: smart_ollama_proxy - INFO - [OPENAI /v1/chat/completions] 收到流式请求，模型: qwen-coder/qwen3-coder-plus, 消息数: 4
[2026-01-27T18:27:45.929111] INFO: smart_ollama_proxy - INFO - 收到OpenAI聊天请求，模型: qwen-coder/qwen3-coder-plus, 流式: True, 消息数: 4
[2026-01-27T18:27:45.929139] INFO: smart_ollama_proxy - INFO - 模型 qwen-coder/qwen3-coder-plus 的路由结果: 1 个后端配置
[2026-01-27T18:27:45.929162] INFO: smart_ollama_proxy - INFO - 模型 qwen-coder/qwen3-coder-plus 的候选路由器: ['qwen-coder.openai_backend']
[2026-01-27T18:27:45.929185] INFO: smart_ollama_proxy - INFO - 路由查找耗时: 0.000秒
[2026-01-27T18:27:45.929204] INFO: smart_ollama_proxy - INFO - OpenAI聊天路由信息 - 模型: qwen-coder/qwen3-coder-plus,  路由器: qwen-coder.openai_backend, 实际模型: qwen3-coder-plus
[2026-01-27T18:27:45.929221] INFO: smart_ollama_proxy - INFO - 后端配置 - URL: https://coding.dashscope.aliyuncs.com/v1, 超时: 30
[2026-01-27T18:27:45.929244] INFO: smart_ollama_proxy - INFO - [OPENAI /v1/chat/completions] 转发前耗时: 0.001秒
[2026-01-27T18:27:45.929260] INFO: smart_ollama_proxy - INFO - [OPENAI /v1/chat/completions] 开始转发到后端
[2026-01-27T18:27:46.535153] INFO: smart_ollama_proxy.backend_router - INFO - [OpenAIBackendRouter._handle_with_openai_sdk] SDK请求完成，耗时: 0.605秒
[32mINFO[0m:     127.0.0.1:5796 - "[1mPOST /v1/chat/completions HTTP/1.1[0m" [32m200 OK[0m
[2026-01-27T18:27:46.535207] INFO: smart_ollama_proxy.backend_router - INFO - [OpenAIBackendRouter] OpenAI SDK请求完成，耗时: 0.606秒
[2026-01-27T18:27:46.535237] INFO: smart_ollama_proxy - INFO - [OPENAI /v1/chat/completions] 后端转发耗时: 0.606秒
[2026-01-27T18:27:46.535259] INFO: smart_ollama_proxy - INFO - [OPENAI /v1/chat/completions] 总耗时: 0.607秒
[31mERROR[0m:    Exception in ASGI application
Traceback (most recent call last):
  File "C:\Python314\Lib\site-packages\uvicorn\protocols\http\httptools_impl.py", line 426, in run_asgi
    result = await app(  # type: ignore[func-returns-value]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        self.scope, self.receive, self.send
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "C:\Python314\Lib\site-packages\uvicorn\middleware\proxy_headers.py", line 84, in __call__
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Python314\Lib\site-packages\fastapi\applications.py", line 1106, in __call__
    await super().__call__(scope, receive, send)
  File "C:\Python314\Lib\site-packages\starlette\applications.py", line 122, in __call__
    await self.middleware_stack(scope, receive, send)
  File "C:\Python314\Lib\site-packages\starlette\middleware\errors.py", line 184, in __call__
    raise exc
  File "C:\Python314\Lib\site-packages\starlette\middleware\errors.py", line 162, in __call__
    await self.app(scope, receive, _send)
  File "C:\Python314\Lib\site-packages\starlette\middleware\exceptions.py", line 79, in __call__
    raise exc
  File "C:\Python314\Lib\site-packages\starlette\middleware\exceptions.py", line 68, in __call__
    await self.app(scope, receive, sender)
  File "C:\Python314\Lib\site-packages\fastapi\middleware\asyncexitstack.py", line 20, in __call__
    raise e
  File "C:\Python314\Lib\site-packages\fastapi\middleware\asyncexitstack.py", line 17, in __call__
    await self.app(scope, receive, send)
  File "C:\Python314\Lib\site-packages\starlette\routing.py", line 718, in __call__
    await route.handle(scope, receive, send)
  File "C:\Python314\Lib\site-packages\starlette\routing.py", line 276, in handle
    await self.app(scope, receive, send)
  File "C:\Python314\Lib\site-packages\starlette\routing.py", line 69, in app
    await response(scope, receive, send)
  File "C:\Python314\Lib\site-packages\starlette\responses.py", line 270, in __call__
    async with anyio.create_task_group() as task_group:
               ~~~~~~~~~~~~~~~~~~~~~~~^^
  File "C:\Python314\Lib\site-packages\anyio\_backends\_asyncio.py", line 597, in __aexit__
    raise exceptions[0]
  File "C:\Python314\Lib\site-packages\starlette\responses.py", line 273, in wrap
    await func()
  File "C:\Python314\Lib\site-packages\starlette\responses.py", line 262, in stream_response
    async for chunk in self.body_iterator:
    ...<2 lines>...
        await send({"type": "http.response.body", "body": chunk, "more_body": True})
  File "D:\PyProject\smart_ollama_proxy\routers\openai_router.py", line 228, in generate
    unified_logger.log_data(
    ~~~~~~~~~~~~~~~~~~~~~~~^
        data_type="input",
        ^^^^^^^^^^^^^^^^^^
    ...<5 lines>...
        log_id=log_id
        ^^^^^^^^^^^^^
    )
    ^
TypeError: UnifiedLoggerCompat.log_data() missing 2 required positional arguments: 'level' and 'message'
