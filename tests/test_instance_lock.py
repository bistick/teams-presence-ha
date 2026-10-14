from pathlib import Path

import pytest

from teams_presence.instance_lock import AlreadyRunningError, acquire_lock


def test_second_lock_fails_until_first_is_released(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "app.lock"
    first = acquire_lock(lock_path)
    with pytest.raises(AlreadyRunningError):
        acquire_lock(lock_path)
    first.close()
    acquire_lock(lock_path).close()
