"""k8s/deploy.sh against a stub kubectl: every post-rollout failure must roll back."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "k8s" / "deploy.sh"
STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$CALLS"
[ -t 0 ] || cat > /dev/null
case "$*" in
  *"rollout history"*) printf 'REVISION\n1 <none>\n2 <none>\n' ;;
  *"delete job"*) [ "${FAIL:-}" != delete ] || exit 1 ;;
  *"create -f"*) [ "${FAIL:-}" != create ] || exit 1 ;;
  *"get job"*)
    n=$(cat "$COUNTER" 2>/dev/null || echo 0); echo $((n + 1)) > "$COUNTER"
    if [ "${FAIL:-}" = transient ] && [ "$n" -lt 2 ]; then exit 1; fi
    if [ "${FAIL:-}" = smoke ]; then [[ "$*" == *failed* ]] && echo 1; exit 0; fi
    [[ "$*" == *succeeded* ]] && echo 1
    exit 0 ;;
esac
exit 0
"""


def _deploy(tmp_path, fail):
    stub = tmp_path / "kubectl"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    calls = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "COUNTER": str(tmp_path / "counter"),
        "FAIL": fail,
        "SMOKE_TIMEOUT_S": "5",
    }
    r = subprocess.run([SCRIPT, "image:tag"], env=env, capture_output=True, text=True)
    return r.returncode, calls.read_text()


def test_success_does_not_roll_back(tmp_path):
    rc, calls = _deploy(tmp_path, "")
    assert rc == 0 and "rollout undo" not in calls


@pytest.mark.parametrize("fail", ["delete", "create", "smoke"])
def test_failure_after_rollout_rolls_back(tmp_path, fail):
    rc, calls = _deploy(tmp_path, fail)
    assert rc == 1 and "rollout undo" in calls


def test_transient_poll_error_is_tolerated(tmp_path):
    rc, calls = _deploy(tmp_path, "transient")
    assert rc == 0 and "rollout undo" not in calls
