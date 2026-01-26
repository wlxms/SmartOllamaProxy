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
python test_api.py
python test_mock.py
python test_refactor.py
python test_client_pool.py
python test_litellm_integration.py

# Run a single test module
python test_api.py

# Test with specific configuration
python test_api.py --host localhost --port 11435
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

## Code Style Guidelines

### Imports Order
Follow this import order with blank lines between groups:
1. Standard library imports
2. Third-party library imports  
3. Local application imports

```python
# Standard library
import os
import logging
from typing import Dict, Any, Optional, List, Tuple

# Third-party
import httpx
import yaml
from fastapi import FastAPI, HTTPException

# Local application
from config_loader import ConfigLoader
from backend_router import BackendRouter
```

### Type Annotations
- Use Python type hints for all function arguments and return values
- Prefer `Optional[T]` over `Union[T, None]`
- Use `Dict[str, Any]` for flexible dictionaries, but prefer specific types when possible

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
- Use Chinese comments for business logic explanations when appropriate

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
- Use YAML for configuration files
- Validate configuration on load
- Provide sensible defaults
- Support environment variable overrides

### Testing Guidelines
- Write tests for new features
- Mock external dependencies (APIs, services)
- Test both success and error cases
- Use async test patterns for async functions

## Project Structure
```
smart_ollama_proxy/
├── main.py                    # FastAPI application entry point
├── config.yaml               # Main configuration file
├── config_loader.py          # Configuration loading and validation
├── backend_router.py         # Backend routing system
├── client_pool.py            # HTTP client management
├── requirements.txt          # Python dependencies
├── run.bat                   # Windows startup script
├── test_*.py                 # Test files
└── README.md                 # Project documentation
```

## Important Notes for Agents

1. **Backward Compatibility**: The proxy must maintain compatibility with Ollama API and OpenAI API formats.

2. **Performance**: Optimize for low latency in request routing and streaming responses.

3. **Error Resilience**: Gracefully handle backend failures with appropriate fallbacks.

4. **Security**: Never log or expose API keys or sensitive tokens.

5. **Streaming**: Support both streaming and non-streaming responses efficiently.

6. **Configuration**: All routing logic should be configurable via YAML without code changes.

7. **Extensibility**: Design new features to be easily configurable and extensible.

When making changes, ensure:
- Tests pass: `python test_api.py`
- Type hints are added for new functions
- Documentation is updated
- Configuration examples are provided
- Backward compatibility is maintained