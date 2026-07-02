import base64
import shlex
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import ServerConfig, get_settings
from app.services import ssh_service
from app.services.ssh_service import CommandResult, OutputHandler


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(get_settings().template_dir / "nginx"),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default=False),
        keep_trailing_newline=True,
    )


def render_config(subdomain: str, upstream_port: int, service_name: str) -> str:
    template = _environment().get_template("reverse_proxy.conf.j2")
    return template.render(
        subdomain=subdomain,
        upstream_port=upstream_port,
        service_name=service_name,
    )


async def validate_and_apply(
    *,
    subdomain: str,
    upstream_port: int,
    service_name: str,
    target: ServerConfig,
    on_output: OutputHandler,
) -> CommandResult:
    rendered = render_config(subdomain, upstream_port, service_name)
    safe_name = "".join(
        character for character in service_name if character.isalnum() or character in "-_"
    )
    if not safe_name:
        raise ValueError("service_name must contain a safe filename character")

    candidate = f"/tmp/seravops-{safe_name}.conf"
    validation_config = f"/tmp/seravops-{safe_name}-nginx.conf"
    encoded_candidate = base64.b64encode(rendered.encode()).decode()
    wrapper = (
        "events {}\nhttp {\n" "  include /etc/nginx/mime.types;\n" f"  include {candidate};\n" "}\n"
    )
    encoded_wrapper = base64.b64encode(wrapper.encode()).decode()
    write_command = (
        f"printf %s {shlex.quote(encoded_candidate)} | base64 -d > {shlex.quote(candidate)} && "
        f"printf %s {shlex.quote(encoded_wrapper)} | base64 -d > {shlex.quote(validation_config)}"
    )
    written = await ssh_service.execute(write_command, target, on_output)
    if written.exit_code != 0:
        return written

    validated = await ssh_service.execute(
        f"nginx -t -c {shlex.quote(validation_config)}", target, on_output
    )
    if validated.exit_code != 0:
        await on_output("stderr", "Nginx validation failed; the active config was not changed.")
        return validated

    destination = Path("/etc/nginx/conf.d") / f"{safe_name}.conf"
    apply_command = (
        f"install -m 0644 {shlex.quote(candidate)} "
        f"{shlex.quote(str(destination))} && nginx -s reload"
    )
    return await ssh_service.execute(apply_command, target, on_output)
