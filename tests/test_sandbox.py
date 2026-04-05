from __future__ import annotations

import os
import time

import pytest

from sandbox import BubblewrapRunner, DirectRunner, NsJailRunner, SandboxResult, create_sandbox_provider


class TestSandboxResult:
    def test_audit_record_format(self):
        result = SandboxResult(exit_code=0, stdout="ok", stderr="", duration_ms=10, truncated=True, sandbox_mode="direct")

        audit = result.to_audit_record()

        assert audit == {
            "type": "sandbox_exec",
            "sandbox_mode": "direct",
            "exit_code": 0,
            "duration_ms": 10,
            "stdout_truncated": True,
        }


@pytest.mark.asyncio
class TestDirectRunner:
    async def test_basic_execution(self):
        runner = DirectRunner()
        result = await runner.execute("echo hello-world")

        assert result.exit_code == 0
        assert "hello-world" in result.stdout.strip()
        assert result.sandbox_mode == "direct"

    async def test_timeout_kill(self):
        runner = DirectRunner()
        start_time = time.time()
        result = await runner.execute("python -c \"import time; time.sleep(100)\"", timeout_seconds=1)
        duration = time.time() - start_time

        assert duration < 5
        assert result.exit_code != 0
        assert "timed out" in result.stderr.lower() or result.exit_code == 124

    async def test_stdout_truncation(self):
        runner = DirectRunner(stdout_limit=1024)
        result = await runner.execute("python -c \"print('A' * 5000)\"")

        assert result.truncated is True
        assert len(result.stdout.encode("utf-8")) <= 1024

    async def test_stderr_capture(self):
        runner = DirectRunner()
        result = await runner.execute("python -c \"import sys; sys.stderr.write('error log')\"")

        assert "error log" in result.stderr

    async def test_workdir_isolation(self, tmp_path):
        runner = DirectRunner()
        workdir = tmp_path / "subdir"
        workdir.mkdir()
        result = await runner.execute("python -c \"import os; print(os.getcwd())\"", workdir=str(workdir))

        assert str(workdir).lower() in result.stdout.lower().strip()

    async def test_env_injection(self):
        runner = DirectRunner()
        result = await runner.execute("python -c \"import os; print(os.environ.get('TEST_VAR'))\"", env={"TEST_VAR": "ops_sentry_val"})

        assert result.stdout.strip() == "ops_sentry_val"


class TestSandboxFactory:
    def test_factory_detection(self, monkeypatch):
        monkeypatch.delenv("SANDBOX_MODE", raising=False)
        monkeypatch.setattr("sandbox.shutil.which", lambda name: None)

        runner = create_sandbox_provider(mode="direct")
        assert runner.mode_name() == "direct"

        monkeypatch.setenv("SANDBOX_MODE", "direct")
        runner = create_sandbox_provider()
        assert runner.mode_name() == "direct"

    def test_factory_autodetects_nsjail(self, monkeypatch):
        monkeypatch.delenv("SANDBOX_MODE", raising=False)
        monkeypatch.setattr("sandbox.shutil.which", lambda name: "/usr/bin/nsjail" if name == "nsjail" else None)
        runner = create_sandbox_provider()

        assert isinstance(runner, NsJailRunner)

    def test_factory_autodetects_bwrap(self, monkeypatch):
        monkeypatch.delenv("SANDBOX_MODE", raising=False)
        monkeypatch.setattr("sandbox.shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None)
        runner = create_sandbox_provider()

        assert isinstance(runner, BubblewrapRunner)


class TestSandboxContracts:
    def test_runner_construction_requires_binary(self, monkeypatch):
        monkeypatch.setattr("sandbox.shutil.which", lambda name: None)

        with pytest.raises(RuntimeError):
            NsJailRunner()
        with pytest.raises(RuntimeError):
            BubblewrapRunner()


@pytest.mark.asyncio
class TestSandboxSecurity:
    async def test_permission_denied_handling(self):
        runner = DirectRunner()
        if os.name == "nt":
            cmd = 'powershell -Command "Write-Error \"Access is denied\"; exit 1"'
        else:
            cmd = 'python -c "import sys; sys.stderr.write(\"Permission denied\"); sys.exit(1)"'

        result = await runner.execute(cmd)

        assert result.exit_code != 0
        assert any(keyword in result.stderr.lower() for keyword in ["denied", "permission", "access"])

    async def test_resource_limit_cpu(self):
        runner = DirectRunner()
        result = await runner.execute("python -c \"while True: pass\"", timeout_seconds=1)

        assert result.exit_code != 0
