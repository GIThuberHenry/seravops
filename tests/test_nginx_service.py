from app.core.config import ServerConfig
from app.services import nginx_service
from app.services.ssh_service import CommandResult


async def test_nginx_does_not_apply_config_when_validation_fails(monkeypatch) -> None:
    commands: list[str] = []
    output: list[tuple[str, str]] = []

    async def fake_execute(command, _target, _on_output):
        commands.append(command)
        return CommandResult(exit_code=1 if "nginx -t" in command else 0)

    async def capture(stream: str, message: str) -> None:
        output.append((stream, message))

    monkeypatch.setattr(nginx_service.ssh_service, "execute", fake_execute)
    result = await nginx_service.validate_and_apply(
        subdomain="demo.example.com",
        upstream_port=8080,
        service_name="demo",
        target=ServerConfig(host="localhost", user="root"),
        on_output=capture,
    )

    assert result.exit_code == 1
    assert len(commands) == 2
    assert not any("install -m" in command for command in commands)
    assert output[-1][0] == "stderr"
