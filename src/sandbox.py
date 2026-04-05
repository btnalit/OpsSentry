from __future__ import annotations

import abc
import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import shutil

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class SandboxResult:
    """沙箱命令执行结果"""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool = False          # stdout 是否被截断
    sandbox_mode: str = "direct"     # 实际使用的 Runner 类型

    def to_audit_record(self) -> dict[str, Any]:
        """输出 OpsLedger 审计记录"""
        return {
            "type": "sandbox_exec",
            "sandbox_mode": self.sandbox_mode,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout_truncated": self.truncated,
        }


class SandboxProvider(abc.ABC):
    """沙箱执行器抽象基类"""

    @abc.abstractmethod
    async def execute(
        self,
        command: str,
        *,
        timeout_seconds: int = 30,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        network: bool = False,
    ) -> SandboxResult:
        """
        执行 Shell 命令并返回结果。
        """
        pass

    @abc.abstractmethod
    def mode_name(self) -> str:
        """返回当前 Runner 名称（"direct" | "nsjail" | "bwrap"）"""
        pass


class DirectRunner(SandboxProvider):
    """
    无强隔离的命令执行器（用于开发/CI环境）。
    """

    DEFAULT_STDOUT_BYTES: int = 1_048_576    # 1 MB
    DEFAULT_STDERR_BYTES: int = 262_144      # 256 KB
    
    # 环境净化白名单
    _ENV_WHITELIST = {"PATH", "HOME", "LANG", "TERM", "PYTHONPATH", "TMP", "TEMP", "USER", "SHELL"}

    def __init__(self, stdout_limit: int | None = None, stderr_limit: int | None = None) -> None:
        self.stdout_limit = stdout_limit or self.DEFAULT_STDOUT_BYTES
        self.stderr_limit = stderr_limit or self.DEFAULT_STDERR_BYTES

    async def execute(
        self,
        command: str,
        *,
        timeout_seconds: int = 30,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        network: bool = True,  # DirectRunner 默认允许网络
    ) -> SandboxResult:
        start_time = time.perf_counter()
        
        # 环境变量净化（阻断 API Key 泄露）
        full_env = self._build_clean_env(env)

        # 启动进程
        # Windows doesn't support preexec_fn=os.setsid
        kwargs = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": workdir,
            "env": full_env,
        }
        if sys.platform != "win32":
            kwargs["preexec_fn"] = os.setsid

        process = await asyncio.create_subprocess_shell(command, **kwargs)

        stdout_data = b""
        stderr_data = b""
        exit_code = -1
        truncated = False

        try:
            # 等待进程执行，带超时
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(), 
                timeout=float(timeout_seconds)
            )
            exit_code = process.returncode if process.returncode is not None else 0
        except asyncio.TimeoutError:
            # 超时处理：SIGTERM -> 2s -> SIGKILL
            await self._kill_process(process)
            # 捕获已有的输出
            stdout_data, stderr_data = await process.communicate()
            stderr_data += b"\n[ERROR] Command timed out"
            exit_code = 124 # Standard timeout exit code
        except Exception as e:
            await self._kill_process(process)
            stderr_data += f"\n[ERROR] Sandbox Exception: {str(e)}".encode()
            exit_code = -1

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        
        # 结果截断处理
        if len(stdout_data) > self.stdout_limit:
            stdout_data = stdout_data[:self.stdout_limit]
            truncated = True
        
        if len(stderr_data) > self.stderr_limit:
            stderr_data = stderr_data[:self.stderr_limit]

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout_data.decode("utf-8", errors="replace"),
            stderr=stderr_data.decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            truncated=truncated,
            sandbox_mode=self.mode_name()
        )

    def _build_clean_env(self, extra_env: dict[str, str] | None) -> dict[str, str]:
        """仅传入白名单环境变量，阻断 API Key 泄露"""
        clean = {k: v for k, v in os.environ.items() if k in self._ENV_WHITELIST}
        if extra_env:
            clean.update(extra_env)
        return clean

    async def _kill_process(self, process: asyncio.subprocess.Process) -> None:
        """优雅终止进程"""
        if process.returncode is not None:
            return

        try:
            if sys.platform == "win32":
                process.kill()
            else:
                # SIGTERM
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    # SIGKILL
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            await process.wait()
        except Exception:
            pass

    def mode_name(self) -> str:
        return "direct"


class NsJailRunner(SandboxProvider):
    """
    NsJail 强隔离命令执行器（生产环境）。
    """
    NSJAIL_BIN: str = "/usr/bin/nsjail"

    def __init__(
        self, 
        binary_path: str | None = None,
        config_path: str = "config/nsjail-default.cfg",
        seccomp_path: str = "config/seccomp-default.json",
        writable_mounts: list[str] | None = None,
        rootfs: str = "/opt/opssentry/rootfs",
    ):
        self.binary_path = binary_path or self.NSJAIL_BIN
        self._config_path = config_path
        self._seccomp_path = seccomp_path
        self._rootfs = rootfs
        self._writable_mounts = writable_mounts or [
            "/tmp/opssentry-work",
            "/root/.accio/sessions",
            "/opt/opssentry/data/ops-queue",
        ]
        
        if sys.platform != "linux":
            # Don't raise in __init__ to allow factory to handle it gracefully if not linux
            pass
        elif not shutil.which(self.binary_path):
             # Don't raise in __init__ to allow factory to handle it gracefully
            pass

    async def execute(
        self,
        command: str,
        *,
        timeout_seconds: int = 30,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        network: bool = False,
    ) -> SandboxResult:
        if sys.platform != "linux" or not shutil.which(self.binary_path):
             raise RuntimeError(f"NsJail not available on this system")

        if self._rootfs == "/":
             raise RuntimeError("Security Breach: NsJail chroot to / is strictly forbidden.")

        start_time = time.perf_counter()
        
        args = [
            self.binary_path,
            "--config", self._config_path,
            "--time_limit", str(timeout_seconds),
            "--user", "nobody",
            "--group", "nogroup",
            "--chroot", self._rootfs,
            "--cwd", workdir or os.getcwd(),
        ]

        if not network:
            args.append("--disable_clone_newnet")
        
        # Seccomp
        if os.path.exists(self._seccomp_path):
            args.extend(["--seccomp_policy_file", self._seccomp_path])

        # Bind mounts
        # Root is readonly by default in our cfg, so we bind mount it
        # Actually nsjail args depend on cfg. Assuming standard usage:
        for mount in self._writable_mounts:
            if os.path.exists(mount):
                args.extend(["--bindmount", f"{mount}:{mount}"])

        # Environment variables
        if env:
            for k, v in env.items():
                args.extend(["--env", f"{k}={v}"])

        args.extend(["--", "/bin/sh", "-c", command])

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout_data, stderr_data = await process.communicate()
        exit_code = process.returncode if process.returncode is not None else -1
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout_data.decode("utf-8", errors="replace"),
            stderr=stderr_data.decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            sandbox_mode=self.mode_name()
        )

    def mode_name(self) -> str:
        return "nsjail"


class BubblewrapRunner(SandboxProvider):
    """
    Bubblewrap 隔离命令执行器（Fallback）。
    """
    BWRAP_BIN: str = "/usr/bin/bwrap"

    def __init__(self, binary_path: str | None = None, rootfs: str = "/opt/opssentry/rootfs"):
        self.binary_path = binary_path or self.BWRAP_BIN
        self._rootfs = rootfs
        if sys.platform != "linux":
            pass
        elif not shutil.which(self.binary_path):
            pass

    async def execute(
        self,
        command: str,
        *,
        timeout_seconds: int = 30,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        network: bool = False,
    ) -> SandboxResult:
        if sys.platform != "linux" or not shutil.which(self.binary_path):
             raise RuntimeError(f"Bubblewrap not available on this system")

        start_time = time.perf_counter()
        
        args = [
            self.binary_path,
            "--ro-bind", self._rootfs, "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--unshare-pid",
            "--die-with-parent",
        ]

        if not network:
            args.append("--unshare-net")
        
        if workdir:
            args.extend(["--chdir", workdir])

        # Env
        if env:
            for k, v in env.items():
                args.extend(["--setenv", k, v])

        args.extend(["/bin/sh", "-c", command])

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(), 
                timeout=float(timeout_seconds)
            )
            exit_code = process.returncode if process.returncode is not None else 0
        except asyncio.TimeoutError:
            process.kill()
            stdout_data, stderr_data = await process.communicate()
            exit_code = 124

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout_data.decode("utf-8", errors="replace"),
            stderr=stderr_data.decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            sandbox_mode=self.mode_name()
        )

    def mode_name(self) -> str:
        return "bwrap"


class BoundedSandboxProvider(SandboxProvider):
    """
    受限执行池 (Bounded Execution Pool) (Phase 5 #41)。
    使用信号量机制限制并发执行的沙箱进程数，防止系统负载过载。
    """
    def __init__(self, inner: SandboxProvider, max_concurrency: int = 8):
        self.inner = inner
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(
        self,
        command: str,
        *,
        timeout_seconds: int = 30,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
        network: bool = False,
    ) -> SandboxResult:
        start_wait = time.perf_counter()
        # 等待可用信号量 (Architecture Spec §2)
        async with self.semaphore:
            wait_ms = int((time.perf_counter() - start_wait) * 1000)
            logger.debug(f"Sandbox acquire wait: {wait_ms}ms")
            
            result = await self.inner.execute(
                command,
                timeout_seconds=timeout_seconds,
                workdir=workdir,
                env=env,
                network=network
            )
            return result

    def mode_name(self) -> str:
        return f"bounded-{self.inner.mode_name()}"

def create_sandbox_provider(mode: str | None = None) -> SandboxProvider:
    """工厂函数：根据环境变量与系统环境返回合适的 Runner (支持 Bounded 包装)"""
    mode = (mode or os.environ.get("SANDBOX_MODE", "auto")).lower()
    max_concurrency = int(os.environ.get("SANDBOX_MAX_CONCURRENCY", "8"))
    
    provider: SandboxProvider
    if mode == "direct":
        provider = DirectRunner()
    elif mode == "nsjail":
        try:
            provider = NsJailRunner()
        except RuntimeError:
            if os.environ.get("SANDBOX_MODE"): raise # Explicitly requested but failed
            provider = DirectRunner()
    elif mode == "bwrap":
        try:
            provider = BubblewrapRunner()
        except RuntimeError:
            if os.environ.get("SANDBOX_MODE"): raise
            provider = DirectRunner()
    else:
        # 自动检测逻辑
        if sys.platform == "linux":
            if shutil.which("nsjail"):
                try: provider = NsJailRunner()
                except RuntimeError: provider = DirectRunner()
            elif shutil.which("bwrap"):
                try: provider = BubblewrapRunner()
                except RuntimeError: provider = DirectRunner()
            else:
                provider = DirectRunner()
        else:
            provider = DirectRunner()

    # 总是使用 BoundedSandboxProvider 包装，以实现反压机制 (Architect Spec §2)
    return BoundedSandboxProvider(provider, max_concurrency=max_concurrency)
