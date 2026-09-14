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
        handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid) # PROCESS_QUERY_INFORMATION
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259 # STILL_ACTIVE
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
        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid) # PROCESS_TERMINATE
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 1)
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

def _worker_entrypoint(send_conn, content: bytes, filename: str, tenant_id: str, client_entity_id: str, max_rows: int):
    """
    Isolated child process entrypoint.
    Executes parsing in independent memory address space.
    Communicates structured outcomes across IPC pipe.
    """
    try:
        # 1. IPC Readiness Handshake: Confirm worker process is active with its OS PID
        try:
            send_conn.send(("READY", os.getpid()))
        except Exception:
            pass

        from app.parsers.registry import registry, UnsupportedFormatError
        txs, summary = registry.parse_file(
            content=content,
            filename=filename,
            tenant_id=tenant_id,
            client_entity_id=client_entity_id
        )
        if max_rows and txs and len(txs) > max_rows:
            send_conn.send(("HTTP_ERROR", 413, f"File '{filename}' exceeds maximum allowed limit of {max_rows} rows."))
            return
        send_conn.send(("OK", txs, summary))
    except HTTPException as he:
        send_conn.send(("HTTP_ERROR", he.status_code, str(he.detail)))
    except Exception as e:
        err_type = type(e).__name__
        err_msg = str(e)
        if "UnsupportedFormatError" in err_type:
            send_conn.send(("UNSUPPORTED_FORMAT", err_msg))
        elif "413" in err_msg or "maximum allowed limit" in err_msg or "exceeds" in err_msg:
            send_conn.send(("HTTP_ERROR", 413, err_msg))
        else:
            send_conn.send(("ERROR", err_type, err_msg))
    except BaseException as be:
        send_conn.send(("FATAL", type(be).__name__, str(be)))
    finally:
        try:
            send_conn.close()
        except Exception:
            pass

class ParserAdmissionTimeout(HTTPException, asyncio.CancelledError):
    """
    Admission timeout exception representing both an HTTP 408 response
    and an asyncio.CancelledError for cancellation semantics.
    """
    def __init__(self, detail: str = "Parser admission timeout"):
        HTTPException.__init__(
            self,
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=detail
        )


class ParserProcessSupervisor:
    """
    Supervises isolated parser processes with:
    - Guaranteed process isolation: each job runs in child process
    - Bounded queue & admission control: immediate 429 when overloaded
    - Complete deadline: covers queue wait, spawn, parse, IPC
    - Structured IPC error propagation: 413/422/408
    - Hard OS kill & confirmed reaping: 0 lingering child processes
    - Zero Durable Retention: kernel reclaims all memory
    """
    def __init__(
        self,
        max_concurrency: Optional[int] = None,
        max_queue_depth: Optional[int] = None,
        default_timeout: Optional[float] = None
    ):
        self._max_concurrency = max_concurrency
        self._max_queue_depth = max_queue_depth
        self._default_timeout = default_timeout
        self._semaphore = None
        self._sem_concurrency = None
        self.waiting_count = 0
        self.last_spawned_pid = None
        self.last_handshake_pid = None
        self.last_job_reaped = None

    @property
    def max_concurrency(self) -> int:
        if self._max_concurrency is not None:
            return self._max_concurrency
        from app.core.config import settings
        return getattr(settings, "PARSER_WORKER_CONCURRENCY", 4)

    @max_concurrency.setter
    def max_concurrency(self, val: int):
        self._max_concurrency = val
        self._semaphore = asyncio.Semaphore(val)
        self._sem_concurrency = val

    @property
    def max_queue_depth(self) -> int:
        if self._max_queue_depth is not None:
            return self._max_queue_depth
        from app.core.config import settings
        return getattr(settings, "PARSER_MAX_QUEUE_DEPTH", 8)

    @max_queue_depth.setter
    def max_queue_depth(self, val: int):
        self._max_queue_depth = val

    @property
    def default_timeout(self) -> float:
        if self._default_timeout is not None:
            return self._default_timeout
        from app.core.config import settings
        return getattr(settings, "PARSER_TIMEOUT_SECONDS", 30.0)

    @default_timeout.setter
    def default_timeout(self, val: float):
        self._default_timeout = val

    @property
    def semaphore(self) -> asyncio.Semaphore:
        current_limit = self.max_concurrency
        if self._semaphore is None or self._sem_concurrency != current_limit:
            self._semaphore = asyncio.Semaphore(current_limit)
            self._sem_concurrency = current_limit
        return self._semaphore

    @semaphore.setter
    def semaphore(self, val: asyncio.Semaphore):
        self._semaphore = val
        self._sem_concurrency = getattr(val, "_value", self.max_concurrency)

    async def parse_file(
        self,
        content: bytes,
        filename: str,
        tenant_id: str,
        client_entity_id: str = "default",
        timeout: Optional[float] = None,
        request_id: Optional[str] = None,
        max_rows: Optional[int] = None
    ) -> Tuple[List[Any], Optional[Any]]:
        effective_timeout = timeout if timeout is not None else self.default_timeout
        file_hash_prefix = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
        req_tag = request_id or "local"
        overall_start = time.monotonic()

        # 1. Admission Control: Reject immediately if queue is full
        if self.waiting_count >= self.max_queue_depth:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Parser queue depth exceeded. Please retry."
            )

        self.waiting_count += 1
        acquired = False
        try:
            time_left_admission = effective_timeout - (time.monotonic() - overall_start)
            if time_left_admission <= 0:
                raise ParserAdmissionTimeout("Parser admission timeout")
            try:
                await asyncio.wait_for(self.semaphore.acquire(), timeout=time_left_admission)
                acquired = True
            except asyncio.TimeoutError:
                raise ParserAdmissionTimeout("Parser admission timeout")
        finally:
            self.waiting_count -= 1

        # 2. Spawn and supervise child process
        proc = None
        recv_conn = None
        send_conn = None
        pid = None

        try:
            time_left_exec = effective_timeout - (time.monotonic() - overall_start)
            if time_left_exec <= 0:
                raise HTTPException(
                    status_code=status.HTTP_408_REQUEST_TIMEOUT,
                    detail="Parser timed out processing file."
                )

            recv_conn, send_conn = multiprocessing.Pipe(duplex=False)
            effective_max_rows = max_rows if max_rows is not None else 10000
            
            proc = multiprocessing.Process(
                target=_worker_entrypoint,
                args=(send_conn, content, filename, tenant_id, client_entity_id, effective_max_rows),
                daemon=True
            )
            proc.start()
            pid = proc.pid
            self.last_spawned_pid = pid
            self.last_handshake_pid = None
            self.last_job_reaped = None

            loop = asyncio.get_running_loop()

            def _poll_result():
                if recv_conn and recv_conn.poll(0.005):
                    return recv_conn.recv()
                return None

            result_payload = None

            while True:
                elapsed = time.monotonic() - overall_start
                if elapsed > effective_timeout:
                    raise asyncio.TimeoutError()

                poll_res = await loop.run_in_executor(None, _poll_result)
                if poll_res is not None:
                    if isinstance(poll_res, tuple) and len(poll_res) == 2 and poll_res[0] == "READY":
                        self.last_handshake_pid = poll_res[1]
                        logger.info(f"Parser worker (PID {self.last_handshake_pid}) confirmed ready via IPC handshake.")
                        continue
                    result_payload = poll_res
                    break

                if not proc.is_alive():
                    if recv_conn and recv_conn.poll(0):
                        poll_res = recv_conn.recv()
                        if isinstance(poll_res, tuple) and len(poll_res) == 2 and poll_res[0] == "READY":
                            self.last_handshake_pid = poll_res[1]
                        else:
                            result_payload = poll_res
                            break
                    raise RuntimeError("Parser worker process crashed unexpectedly.")

                await asyncio.sleep(0.005)

            status_type = result_payload[0]
            if status_type == "OK":
                _, txs, summary = result_payload
                return txs, summary
            elif status_type == "HTTP_ERROR":
                _, err_code, err_detail = result_payload
                raise HTTPException(status_code=err_code, detail=err_detail)
            elif status_type == "UNSUPPORTED_FORMAT":
                _, err_msg = result_payload
                from app.parsers.registry import UnsupportedFormatError
                raise UnsupportedFormatError(err_msg)
            elif status_type == "ERROR":
                _, err_type, err_msg = result_payload
                raise RuntimeError(f"Parser error ({err_type}): {err_msg}")
            else:
                _, err_type, err_msg = result_payload
                raise RuntimeError(f"Parser fatal failure ({err_type}): {err_msg}")

        except asyncio.TimeoutError:
            if pid:
                if proc and proc.is_alive():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                _hard_kill_pid(pid)
                if proc:
                    proc.join(timeout=0.1)
                if _pid_exists(pid):
                    _hard_kill_pid(pid)
                    if proc:
                        proc.join(timeout=0.1)

                is_reaped = (not _pid_exists(pid)) and (proc is None or not proc.is_alive())
                self.last_job_reaped = is_reaped
                if is_reaped:
                    logger.error(
                        f"Parser worker (PID {pid}) timed out after {effective_timeout}s "
                        f"for request {req_tag} (file_{file_hash_prefix}). Killed and reaped."
                    )
                else:
                    logger.critical(
                        f"CRITICAL: Parser worker (PID {pid}) failed to terminate after hard kill attempt! Lingering process detected."
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Parser worker termination failure."
                    )

            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="Parser timed out processing file."
            )
        finally:
            if recv_conn:
                try:
                    recv_conn.close()
                except Exception:
                    pass
            if send_conn:
                try:
                    send_conn.close()
                except Exception:
                    pass
            if proc and proc.is_alive():
                try:
                    proc.kill()
                except Exception:
                    pass
                if pid:
                    _hard_kill_pid(pid)
                proc.join(timeout=0.05)
            if pid:
                self.last_job_reaped = (not _pid_exists(pid)) and (proc is None or not proc.is_alive())
            if acquired:
                self.semaphore.release()

parser_supervisor = ParserProcessSupervisor()
