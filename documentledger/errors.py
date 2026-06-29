from __future__ import annotations

import json
from typing import IO

import click


class DocumentledgerError(click.ClickException):
    def __init__(
        self,
        code: str,
        message: str,
        remediation: list[str] | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation or []

    def show(self, file: IO[str] | None = None) -> None:
        click.echo(
            json.dumps(
                {
                    "ok": False,
                    "command": "unknown",
                    "error": {
                        "code": self.code,
                        "message": self.message,
                        "remediation": self.remediation,
                    },
                    "events": [],
                },
                sort_keys=True,
            ),
            file=file,
        )
