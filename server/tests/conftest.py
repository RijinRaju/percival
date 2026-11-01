import pytest

from percival_server.config import DEVELOPMENT, ServerConfig


@pytest.fixture
def config(tmp_path):
    return ServerConfig(
        env=DEVELOPMENT,
        secret_key="test-secret-" + "x" * 40,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secure_cookies=False,
        static_dir=None,
        run_consumer=False,
    )
