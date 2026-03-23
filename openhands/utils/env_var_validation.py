"""Utilities for validating environment variable names."""

import re

# Pattern for valid environment variable names per POSIX standard.
# Must start with a letter or underscore, contain only alphanumeric characters and underscores.
ENV_VAR_NAME_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def is_valid_env_var_name(name: str) -> bool:
    """Check if a name is valid for use as an environment variable.

    Valid names must:
    - Start with a letter (a-z, A-Z) or underscore (_)
    - Contain only alphanumeric characters (a-z, A-Z, 0-9) and underscores (_)

    Args:
        name: The name to validate.

    Returns:
        True if the name is valid, False otherwise.
    """
    if not name:
        return False
    return bool(ENV_VAR_NAME_PATTERN.match(name))


def validate_env_var_name(name: str, field_name: str = 'name') -> None:
    """Validate that a name is valid for use as an environment variable.

    Args:
        name: The name to validate.
        field_name: The name of the field being validated (for error messages).

    Raises:
        ValueError: If the name is invalid.
    """
    if not is_valid_env_var_name(name):
        raise ValueError(
            f"Invalid {field_name} '{name}'. Must start with a letter or underscore, "
            'and contain only alphanumeric characters and underscores.'
        )
