import pytest

from .fakeapi import FakeApiServer


@pytest.fixture
def fake_api():
    server = FakeApiServer()
    server.start()
    yield server
    server.stop()
