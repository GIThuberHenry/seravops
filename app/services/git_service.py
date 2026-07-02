import shlex

from app.core.config import ServerConfig
from app.services import ssh_service
from app.services.ssh_service import CommandResult, OutputHandler


async def pull(
    repository_path: str, target: ServerConfig, on_output: OutputHandler
) -> CommandResult:
    command = f"git -C {shlex.quote(repository_path)} pull --ff-only"
    return await ssh_service.execute(command, target, on_output)


async def clone(
    repository_url: str,
    destination: str,
    target: ServerConfig,
    on_output: OutputHandler,
) -> CommandResult:
    command = f"git clone {shlex.quote(repository_url)} {shlex.quote(destination)}"
    return await ssh_service.execute(command, target, on_output)
