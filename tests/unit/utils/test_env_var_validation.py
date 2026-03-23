"""Tests for environment variable name validation utility."""

import pytest

from openhands.utils.env_var_validation import (
    is_valid_env_var_name,
    validate_env_var_name,
)


class TestIsValidEnvVarName:
    """Tests for is_valid_env_var_name function."""

    @pytest.mark.parametrize(
        'name',
        [
            'MY_VAR',
            'my_var',
            'MyVar',
            '_PRIVATE',
            '_',
            '__',
            'A',
            'a',
            'VAR123',
            '_123',
            'API_KEY',
            'DATABASE_URL',
            'GITHUB_TOKEN',
        ],
    )
    def test_valid_names(self, name: str):
        """Test that valid environment variable names are accepted."""
        assert is_valid_env_var_name(name) is True

    @pytest.mark.parametrize(
        'name',
        [
            'MY-VAR',  # Contains hyphen
            'MY VAR',  # Contains space
            'MY.VAR',  # Contains period
            '123VAR',  # Starts with digit
            '1',  # Single digit
            '-VAR',  # Starts with hyphen
            'MY@VAR',  # Contains @
            'MY$VAR',  # Contains $
            'MY#VAR',  # Contains #
            'MY!VAR',  # Contains !
            'MY%VAR',  # Contains %
            'MY^VAR',  # Contains ^
            'MY&VAR',  # Contains &
            'MY*VAR',  # Contains *
            'MY(VAR',  # Contains (
            'MY)VAR',  # Contains )
            'MY+VAR',  # Contains +
            'MY=VAR',  # Contains =
            'MY[VAR',  # Contains [
            'MY]VAR',  # Contains ]
            'MY{VAR',  # Contains {
            'MY}VAR',  # Contains }
            'MY|VAR',  # Contains |
            'MY\\VAR',  # Contains backslash
            'MY/VAR',  # Contains forward slash
            'MY?VAR',  # Contains ?
            'MY<VAR',  # Contains <
            'MY>VAR',  # Contains >
            'MY,VAR',  # Contains comma
            'MY:VAR',  # Contains colon
            'MY;VAR',  # Contains semicolon
            "MY'VAR",  # Contains single quote
            'MY"VAR',  # Contains double quote
            'MY`VAR',  # Contains backtick
            'MY~VAR',  # Contains tilde
        ],
    )
    def test_invalid_names_special_chars(self, name: str):
        """Test that names with special characters are rejected."""
        assert is_valid_env_var_name(name) is False

    @pytest.mark.parametrize(
        'name',
        [
            '',
            '0VAR',
            '9_TEST',
        ],
    )
    def test_invalid_names_empty_or_starts_with_digit(self, name: str):
        """Test that empty names and names starting with digits are rejected."""
        assert is_valid_env_var_name(name) is False


class TestValidateEnvVarName:
    """Tests for validate_env_var_name function."""

    def test_valid_name_no_exception(self):
        """Test that valid names do not raise exceptions."""
        # Should not raise any exception
        validate_env_var_name('MY_VALID_VAR')
        validate_env_var_name('_PRIVATE_VAR')
        validate_env_var_name('API_KEY_123')

    def test_invalid_name_raises_value_error(self):
        """Test that invalid names raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_env_var_name('MY-INVALID-VAR')
        assert "Invalid name 'MY-INVALID-VAR'" in str(exc_info.value)
        assert 'Must start with a letter or underscore' in str(exc_info.value)
        assert 'alphanumeric characters and underscores' in str(exc_info.value)

    def test_empty_name_raises_value_error(self):
        """Test that empty names raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_env_var_name('')
        assert "Invalid name ''" in str(exc_info.value)

    def test_starts_with_digit_raises_value_error(self):
        """Test that names starting with digits raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_env_var_name('1VAR')
        assert "Invalid name '1VAR'" in str(exc_info.value)

    def test_custom_field_name_in_error_message(self):
        """Test that custom field_name appears in error message."""
        with pytest.raises(ValueError) as exc_info:
            validate_env_var_name('MY-VAR', field_name='secret name')
        assert "Invalid secret name 'MY-VAR'" in str(exc_info.value)

    def test_default_field_name_in_error_message(self):
        """Test that default field_name 'name' appears in error message."""
        with pytest.raises(ValueError) as exc_info:
            validate_env_var_name('MY-VAR')
        assert "Invalid name 'MY-VAR'" in str(exc_info.value)
