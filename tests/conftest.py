import pytest

# Note: nothing here may import ctranslate2 or numpy. The real translation model
# is exercised only in fresh subprocesses (tests/test_integration_translate.py)
# because conda's numpy and ctranslate2 cannot share a process (lesson #312).


@pytest.fixture
def anyio_backend():
    # mcp ships anyio; pin the backend so pytest does not also try trio.
    return "asyncio"
