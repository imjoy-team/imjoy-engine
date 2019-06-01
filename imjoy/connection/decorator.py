"""Provide a decorator to register event handlers."""


def socketio_handler(event, namespace=None):
    """Register a socketio handler via decorator."""

    def wrapper(func):
        """Decorate a ws event handler."""
        # pylint: disable=protected-access
        func._ws_event = event
        func._ws_namespace = namespace
        return func

    return wrapper


def partial_coro(func, *args, **keywords):
    """Return a partial coroutine."""
    # https://docs.python.org/3/library/functools.html#functools.partial
    async def wrapper(*fargs, **fkeywords):
        """Wrap the coroutine function."""
        newkeywords = keywords.copy()
        newkeywords.update(fkeywords)
        return await func(*args, *fargs, **newkeywords)

    wrapper.func = func
    wrapper.args = args
    wrapper.keywords = keywords
    return wrapper
