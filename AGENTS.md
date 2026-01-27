# Smart Ollama Proxy - Agent Guidelines

This document provides guidelines for AI agents working on the Smart Ollama Proxy project, including build commands, testing procedures, and code style conventions.

## Build and Development Commands

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# For development with additional tools (optional)
pip install black ruff mypy pytest httpx
```

### Running the Application
```bash
# Development server (Windows)
python main.py

# Alternative with uvicorn (production)
uvicorn main:app --host 0.0.0.0 --port 11435 --reload

# Windows batch script
run.bat
```

### Testing Commands
```bash
# Run all test scripts
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_api.py -v

# Run a single test function
python -m pytest tests/test_api.py::test_api_endpoints -v

# Run tests with coverage
python -m pytest tests/ --cov=. --cov-report=html

# Alternative: Run test scripts directly
python tests/test_api.py
python tests/test_mock.py
python tests/test_refactor.py
python tests/test_client_pool.py
python tests/test_litellm_integration.py
python tests/test_priority_fallback.py
```

### Code Quality Checks
```bash
# Type checking (if mypy is installed)
mypy --ignore-missing-imports .

# Formatting check (if black is installed)
black --check .

# Linting (if ruff is installed)
ruff check .
```

## Project Structure
```
smart_ollama_proxy/
├── main.py                    # FastAPI application entry point
├── config.yaml               # Main configuration file
├── config_loader.py          # Configuration loading and validation
├── client_pool.py            # HTTP client management
├── stream_logger.py          # Async logging system
├── utils.py                  # Utility functions
├── requirements.txt          # Python dependencies
├── run.bat                   # Windows startup script
├── README.md                 # Project documentation
├── AGENTS.md                 # This file
├── routers/                  # Backend router implementations
│   ├── __init__.py
│   ├── base_router.py        # Base router interface
│   ├── backend_router_factory.py # Router factory
│   ├── openai_router.py      # OpenAI-compatible API router
│   ├── litellm_router.py     # LiteLLM SDK router
│   ├── ollama_router.py      # Local Ollama router
│   └── mock_router.py        # Mock router for testing
└── tests/                    # Test files
    ├── test_api.py           # API endpoint tests
    ├── test_mock.py          # Mock backend tests
    ├── test_refactor.py      # Refactoring tests
    ├── test_client_pool.py   # Client pool tests
    ├── test_litellm_integration.py # LiteLLM integration tests
    ├── test_priority_fallback.py # Backend priority tests
    ├── test_litellm_serialization.py # LiteLLM serialization tests
    ├── test_new_architecture.py # Architecture tests
    └── verify_fixes.py       # Fix verification tests
```

## Code Style Guidelines

### Imports Order
Follow this import order with blank lines between groups:
1. Standard library imports
2. Third-party library imports  
3. Local application imports

```python
# Standard library
import os
import sys
import io
import logging
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

# Third-party
import httpx
import yaml
import orjson
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# Local application
from config_loader import ConfigLoader, ModelRouter, BackendConfig
from routers.backend_router_factory import BackendRouterFactory, BackendManager
from stream_logger import init_global_logger, configure_root_logging
```

### Type Annotations
- Use Python type hints for all function arguments and return values
- Prefer `Optional[T]` over `Union[T, None]`
- Use `Dict[str, Any]` for flexible dictionaries, but prefer specific types when possible
- Use `List[T]` for lists, `Tuple[T1, T2]` for tuples

```python
def process_model_config(
    config_data: Dict[str, Any], 
    model_group: str
) -> Optional[ModelConfig]:
    """Process model configuration with validation."""
    if not config_data:
        return None
    # Implementation
```

### Naming Conventions
- **Variables and functions**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private members**: `_leading_underscore` for non-public methods/attributes
- **Async functions**: Use `async` prefix or suffix indicating async nature

```python
# Good examples
API_TIMEOUT = 30
DEFAULT_PORT = 11435
model_config = load_config()
logger = logging.getLogger(__name__)

class BackendRouter:
    def __init__(self):
        self._client_pool = ClientPool()
    
    async def handle_request(self, request: Request) -> Response:
        """Async request handler."""
```

### Error Handling
- Use specific exception types when possible
- Log exceptions with appropriate levels
- Provide meaningful error messages
- Use HTTPException for API errors with status codes
- Always include context in error messages

```python
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

async def process_request(request_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = await backend_call(request_data)
        return result
    except httpx.TimeoutException as e:
        logger.error(f"Backend timeout: {e}")
        raise HTTPException(status_code=504, detail="Backend timeout")
    except httpx.HTTPStatusError as e:
        logger.error(f"Backend error {e.response.status_code}: {e}")
        raise HTTPException(
            status_code=502, 
            detail=f"Backend error: {e.response.status_code}"
        )
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

### Logging
- Use module-level loggers: `logger = logging.getLogger(__name__)`
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Include context in log messages
- Avoid logging sensitive data (API keys, tokens)
- Use the project's `stream_logger.py` for async logging

```python
import logging

logger = logging.getLogger(__name__)

def validate_config(config: Dict[str, Any]) -> bool:
    if not config.get("api_key"):
        logger.warning("API key missing in configuration")
        return False
    logger.debug(f"Configuration validated: {len(config)} items")
    return True
```

### Documentation
- Use docstrings for all public functions, classes, and modules
- Follow Google-style docstring format
- Include parameter descriptions, return values, and raised exceptions
- Use Chinese comments for business logic explanations when appropriate (this project has Chinese documentation)

```python
class ModelConfig:
    """模型配置类，用于管理和验证模型配置。
    
    Attributes:
        model_group: 模型组名称，如 'deepseek'、'openai'
        available_models: 可用模型列表
        backend_config: 后端配置信息
    """
    
    def __init__(self, model_group: str, config_data: Dict[str, Any]):
        """初始化模型配置。
        
        Args:
            model_group: 模型组标识符
            config_data: 配置数据字典
            
        Raises:
            ValueError: 当配置数据无效时
        """
        # Implementation
```

### Async/Await Patterns
- Use `async/await` for all I/O operations
- Use `asyncio.gather()` for parallel operations when appropriate
- Handle cancellation properly with try/except blocks
- Use timeout for async operations
- Always use `async with` for context managers

```python
import asyncio
import httpx
from typing import List

async def fetch_multiple_endpoints(
    urls: List[str], 
    timeout: float = 30.0
) -> List[Dict[str, Any]]:
    """Fetch multiple endpoints concurrently."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for response in responses:
            if isinstance(response, Exception):
                logger.error(f"Request failed: {response}")
                results.append({"error": str(response)})
            else:
                results.append(response.json())
        return results
```

### Configuration Management
- Use YAML for configuration files (`config.yaml`)
- Validate configuration on load
- Provide sensible defaults
- Support environment variable overrides
- Use the `ConfigLoader` class for loading and validating configs

### Testing Guidelines
- Write tests for new features in the `tests/` directory
- Mock external dependencies (APIs, services)
- Test both success and error cases
- Use async test patterns for async functions
- Follow pytest conventions
- Use descriptive test function names

```python
# Example test pattern
async def test_api_endpoints():
    """Test API endpoints work correctly."""
    # Setup
    # Execution
    # Assertion
    pass
```

## Important Notes for Agents

1. **Backward Compatibility**: The proxy must maintain compatibility with Ollama API and OpenAI API formats.

2. **Performance**: Optimize for low latency in request routing and streaming responses.

3. **Error Resilience**: Gracefully handle backend failures with appropriate fallbacks.

4. **Security**: Never log or expose API keys or sensitive tokens.

5. **Streaming**: Support both streaming and non-streaming responses efficiently.

6. **Configuration**: All routing logic should be configurable via YAML without code changes.

7. **Extensibility**: Design new features to be easily configurable and extensible.

8. **Async Patterns**: This project heavily uses async/await - ensure all I/O operations are async.

9. **Type Safety**: Use type hints consistently throughout the codebase.

10. **Logging**: Use the project's async logging system (`stream_logger.py`) for performance.

## Development Workflow

When making changes, ensure:
- Tests pass: `python -m pytest tests/`
- Type hints are added for new functions
- Documentation is updated (docstrings and README if needed)
- Configuration examples are provided if adding new config options
- Backward compatibility is maintained
- Async patterns are followed for I/O operations

## VS Code Configuration

The project includes a `.vscode/settings.json` file that adds the `routers/` directory to Python analysis paths:
```json
{
    "python.analysis.extraPaths": [
        "./routers"
    ]
}
```

## Dependencies

Key dependencies (see `requirements.txt`):
- `fastapi==0.104.1`: Web framework
- `httpx[http2]==0.25.2`: Async HTTP client
- `pydantic>=2.0.3,<3`: Data validation
- `uvicorn[standard]==0.24.0`: ASGI server
- `pyyaml>=6.0`: YAML parsing
- `orjson>=3.9.0`: Fast JSON parsing
- `litellm>=1.0.0`: Optional LiteLLM SDK integration

## Common Issues and Solutions

### Import Errors
If you see import errors when running tests, ensure you're in the project root directory and Python can find the modules:
```bash
cd /path/to/smart_ollama_proxy
python -m pytest tests/
```

### Configuration Issues
- Check `config.yaml` syntax (must be valid YAML)
- Ensure API keys are properly formatted
- Verify network connectivity to backend services

### Async Issues
- Always use `await` with async functions
- Use `async with` for context managers
- Handle exceptions in async code properly

### Testing Issues
- Mock external API calls in tests
- Use `pytest-asyncio` for async tests
- Run tests from project root directory