"""Test the testing framework."""
import pytest


def test_framework_pass():
    """Test that the testing framework works and a test can pass."""
    assert True


@pytest.mark.xfail
def test_framework_fail():
    """Test that the testing framework works and a test can fail."""
    assert False
