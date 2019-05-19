"""Provide utils for aiohttp."""
from aiohttp import streamer


@streamer
async def file_sender(writer, file_path=None):
    """Read a large file chunk by chunk and send it through HTTP.

    Do not read the chunks into memory.
    """
    with open(file_path, "rb") as f:
        chunk = f.read(2 ** 16)
        while chunk:
            await writer.write(chunk)
            chunk = f.read(2 ** 16)
