import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncssh

from app.core.config import ServerConfig

OutputHandler = Callable[[str, str], Awaitable[None]]


@dataclass(slots=True)
class CommandResult:
    exit_code: int


async def _stream_reader(
    reader: asyncio.StreamReader | asyncssh.SSHReader[str],
    stream: str,
    on_output: OutputHandler,
) -> None:
    async for line in reader:
        await on_output(stream, line.rstrip("\n"))


async def _execute_local(command: str, on_output: OutputHandler) -> CommandResult:
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    await asyncio.gather(
        _stream_reader(process.stdout, "stdout", on_output),
        _stream_reader(process.stderr, "stderr", on_output),
    )
    return CommandResult(exit_code=await process.wait())


async def _execute_remote(
    command: str, target: ServerConfig, on_output: OutputHandler
) -> CommandResult:
    connect_options: dict = {
        "host": target.host,
        "port": target.port,
        "username": target.user,
        "known_hosts": None,
    }
    if target.key_path:
        connect_options["client_keys"] = [target.key_path]

    async with asyncssh.connect(**connect_options) as connection:
        process = await connection.create_process(command)
        await asyncio.gather(
            _stream_reader(process.stdout, "stdout", on_output),
            _stream_reader(process.stderr, "stderr", on_output),
        )
        await process.wait()
        return CommandResult(exit_code=process.exit_status or 0)


async def execute(command: str, target: ServerConfig, on_output: OutputHandler) -> CommandResult:
    if target.host in {"localhost", "127.0.0.1", "::1"}:
        return await _execute_local(command, on_output)
    return await _execute_remote(command, target, on_output)
