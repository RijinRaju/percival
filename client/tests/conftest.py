import fakeredis
import pytest

from percival import runtime
from percival.config import Settings


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


@pytest.fixture
def rt(fake_server):
    """A configured runtime backed by fakeredis."""

    def factory(url):
        return fakeredis.FakeRedis(server=fake_server)

    settings = Settings.build(redis_url="redis://fake/0", code_version="v1")
    yield runtime.configure(settings, client_factory=factory)
    runtime.reset()
