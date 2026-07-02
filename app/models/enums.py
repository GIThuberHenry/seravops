from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    DEVELOPER = "developer"


class StepKind(StrEnum):
    COMMAND = "command"
    GIT_PULL = "git_pull"
    NGINX = "nginx"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class LogStream(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"
    SYSTEM = "system"
