"""Provide utilities that should not be aware of ImJoy engine."""


class Registry(dict):
    """Registry of items."""

    # https://github.com/home-assistant/home-assistant/blob/
    # 2a9fd9ae269e8929084e53ab12901e96aec93e7d/homeassistant/util/decorator.py
    def register(self, name):
        """Return decorator to register item with a specific name."""

        def decorator(func):
            """Register decorated function."""
            self[name] = func
            return func

        return decorator
