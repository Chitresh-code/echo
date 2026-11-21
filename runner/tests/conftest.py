import sys
import uuid
from pathlib import Path

import pytest

from app import jail

FAKE_NSJAIL = Path(__file__).parent / "helpers" / "fake_nsjail.py"


@pytest.fixture
def settings(tmp_path):
    return jail.Settings(data_dir=tmp_path, network=True, timeout_max=30, memory_mb=4096)


@pytest.fixture
def fake_settings(tmp_path):
    """Settings whose nsjail is a stand-in that runs the command without a jail, so the service
    can be tested on any machine."""
    FAKE_NSJAIL.chmod(0o755)
    return jail.Settings(data_dir=tmp_path, network=True, timeout_max=30, memory_mb=4096, nsjail=str(FAKE_NSJAIL))


@pytest.fixture
def ws_id():
    return uuid.uuid4().hex
