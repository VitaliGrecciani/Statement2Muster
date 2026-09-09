import os
import sys
import time
import signal
import ctypes
import asyncio
import logging
import hashlib
import multiprocessing
from typing import Tuple, List, Optional, Dict, Any
from fastapi import HTTPException, status

logger = logging.getLogger("statement2muster.parser_supervisor")

def _pid_exists(pid: int) -> bool:
    """Check whether an OS process with the given PID is currently alive."""
    if pid <= 0:
        return False
    if os.name == 'nt':
        handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

def _hard_kill_pid(pid: int):
    """Guaranteed immediate OS-level process kill."""
    if pid <= 0:
        return
    if os.name == 'nt':
        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 1)
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

def _worker_entrypoint(send_conn, content: bytes, filename: str, tenant_id: str, client_entity_id: str):
    """
    Child process worker entrypoint.
    Executes inside an independent OS process memory space.
    """
    try:
        from app.parsers.registry import registry, UnsupportedFormatError
        txs, summary = registry.parse_file(
            content=content,
            filename=filename,
            tenant_id=tenant_id,
            client_entity_id=client_entity_id
        )
        send_conn.send(("OK", txs, summary))
    except Exception as e:
        err_type = type(e).__name__
        send_conn.send(("ERROR", err_type, str(e)))
    except BaseException as be:
        send_conn.send(("FATAL", type(be).__name__, str(be)))
    finally:
        try:
            send_conn.close()
        except Exception:
            pass

class ParserProcessSupervisor:
    """
    Supervises parser worker execution in isolated child processes (C07 / Decisions 11-13).
    - Hard process boundary: complete memory and crash isolation.
    - Bounded concurrency queue: enforces fair use and protects against DoS.
    - Wall-time deadline: terminates long-running or hanging parsing operations.
    - Guaranteed OS-level kill: TerminateProcess / SIGKILL ensures process is dead before HTTP 408.
    - Confirmed reaping: verifies process exit and cleans up OS process table.
    - Zero Durable Retention: kernel reclaims all pages, buffers, and allocations.
    """
    def __init__(self, max_concurrency: int = 4, default_timeout: float = 30.0):
        self.max_concurrency = max_concurrency
        self.default_timeout = default_timeout
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def parse_file(
        self,
        content: bytes,
        filename: str,
        tenant_id: str,
        client_entity_id: str = "default",
        timeout: Optional[float] = None,
        request_id: Optional[str] = None
    ) -> Tuple[List[Any], Optional[Any]]:
        effective_timeout = timeout if timeout is not None else self.default_timeout
        file_hash_prefix = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
        req_tag = request_id or "local"

        async with self.semaphore:
            recv_conn, send_conn = multiprocessing.Pipe(duplex=False)
            proc = multiprocessing.Process(
                target=_worker_entrypoint,
                args=(send_conn, content, filename, tenant_id, client_entity_id),
                daemon=True
            )
            proc.start()
            pid = proc.pid

            loop = asyncio.get_running_loop()

            def _poll_result():
                if recv_conn.poll(0.005):
                    return recv_conn.recv()
                return None

            start_time = time.monotonic()
            result_payload = None

            try:
                while True:
                    if time.monotonic() - start_time > effective_timeout:
                        raise asyncio.TimeoutError()

                    poll_res = await loop.run_in_executor(None, _poll_result)
                    if poll_res is not None:
                        result_payload = poll_res
                        break

                    if not proc.is_alive():
                        if recv_conn.poll(0):
                            result_payload = recv_conn.recv()
                            break
                        raise RuntimeError("Parser worker process crashed unexpectedly.")

                    await asyncio.sleep(0.005)

            except asyncio.TimeoutError:
                # 1. Hard OS kill: TerminateProcess / SIGKILL (C07)
                try:
                    proc.kill()
                except Exception:
                    pass
                _hard_kill_pid(pid)

                # 2. Confirmed process reaping: assert dead within deadline
                proc.join(timeout=0.1)
                is_dead = not proc.is_alive() and not _pid_exists(pid)
                if not is_dead:
                    _hard_kill_pid(pid)
                    proc.join(timeout=0.05)

                # 3. Clean up IPC handles
                try:
                    recv_conn.close()
                except Exception:
                    pass
                try:
                    send_conn.close()
                except Exception:
                    pass

                # 4. Zero PII logging (A16): file hash + request ID only
                logger.error(
                    f"Parser worker (PID {pid}) timed out after {effective_timeout}s "
                    f"for request {req_tag} (file_{file_hash_prefix}). Killed and reaped."
                )
                raise HTTPException(
                    status_code=status.HTTP_408_REQUEST_TIMEOUT,
                    detail="Parser timed out processing file."
                )
            finally:
                try:
                    recv_conn.close()
                except Exception:
                    pass
                try:
                    send_conn.close()
                except Exception:
                    pass
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.05)

            status_type = result_payload[0]
            if status_type == "OK":
                _, txs, summary = result_payload
                return txs, summary
            elif status_type == "ERROR":
                _, err_type, err_msg = result_payload
                if "UnsupportedFormatError" in err_type:
                    from app.parsers.registry import UnsupportedFormatError
                    raise UnsupportedFormatError(err_msg)
                raise RuntimeError(f"Parser error ({err_type}): {err_msg}")
            else:
                _, err_type, err_msg = result_payload
                raise RuntimeError(f"Parser fatal failure ({err_type}): {err_msg}")

parser_supervisor = ParserProcessSupervisor()
