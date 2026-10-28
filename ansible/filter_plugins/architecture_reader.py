"""Validate the metadata reader contract without including inputs in errors."""

import re

from ansible.errors import AnsibleFilterError


def architecture_reader_contract(value):
    try:
        if not isinstance(value, dict) or set(value) != {"databases", "infisical_path"}:
            raise ValueError
        databases = value["databases"]
        if not isinstance(databases, list) or not databases or len(databases) > 32:
            raise ValueError
        names = set()
        for database in databases:
            if not isinstance(database, dict) or set(database) != {"name", "schemas"}:
                raise ValueError
            name = database["name"]
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) or name in names:
                raise ValueError
            names.add(name)
            schemas = database["schemas"]
            if (not isinstance(schemas, list) or not schemas or len(set(schemas)) != len(schemas)
                    or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", s)
                           or s.startswith("pg_") or s == "information_schema" for s in schemas)):
                raise ValueError
        path = value["infisical_path"]
        if not re.fullmatch(r"/[a-z][a-z0-9/-]*", path) or ".." in path or "//" in path:
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError):
        raise AnsibleFilterError("Architecture reader requires explicit databases, schemas and Infisical path") from None


def architecture_reader_password(value):
    if not isinstance(value, str) or not 48 <= len(value) <= 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise AnsibleFilterError("Architecture reader password must be a strong Infisical-managed URL-safe value")
    return value


class FilterModule:
    def filters(self):
        return {
            "architecture_reader_contract": architecture_reader_contract,
            "architecture_reader_password": architecture_reader_password,
        }
