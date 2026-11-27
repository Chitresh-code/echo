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
    # The fake also stands in for nsenter, since both run what follows their first `--`; `true`
    # stands in for ip, so no namespace is made.
    return jail.Settings(
        data_dir=tmp_path, network=True, timeout_max=30, memory_mb=4096,
        nsjail=str(FAKE_NSJAIL), nsenter=str(FAKE_NSJAIL), ip="true", netns_dir=tmp_path / "netns",
    )


@pytest.fixture
def ws_id():
    return uuid.uuid4().hex
