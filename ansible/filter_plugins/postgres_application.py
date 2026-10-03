"""Validate an application's protected URI without returning it in errors."""

import re
from urllib.parse import unquote, urlsplit

from ansible.errors import AnsibleFilterError


def postgres_application_credential(value, application):
    try:
        parsed = urlsplit(value)
        role = application["role"]
        database = application["database"]
        password = unquote(parsed.password or "")
        if not (
            re.fullmatch(r"[a-z][a-z0-9_]{0,62}", role)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database)
            and parsed.scheme == "postgresql+psycopg"
            and unquote(parsed.username or "") == role
            and unquote(parsed.path) == "/" + database
            and parsed.hostname == application["host"]
            and parsed.port == application["port"]
            and not parsed.query
            and not parsed.fragment
            and len(password) >= 32
            and all(32 < ord(character) < 127 for character in password)
        ):
            raise ValueError
        return {"password": password}
    except (ValueError, TypeError, KeyError):
        raise AnsibleFilterError(
            "Application database URL is missing or violates the selected contract"
        ) from None


class FilterModule:
    def filters(self):
        return {"postgres_application_credential": postgres_application_credential}
