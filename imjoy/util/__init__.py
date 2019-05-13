"""Provide utilities that should not be aware of ImJoy engine."""
import os
import string
import sys

if sys.platform == "win32":
    from ctypes import windll

    def get_drives():
        """Return windows drives."""
        drives = []
        bitmask = windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drives.append(os.path.abspath(letter + ":/"))
            bitmask >>= 1
        return drives


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


def parseRepos(requirements, work_dir):
    """Return a list of repositories from a list of requirements."""
    repos = []
    if type(requirements) is list:
        requirements = [str(r) for r in requirements]
        for r in requirements:
            if ":" in r:
                rs = r.split(":")
                tp, libs = rs[0], ":".join(rs[1:])
                tp, libs = tp.strip(), libs.strip()
                libs = [l.strip() for l in libs.split(" ") if l.strip() != ""]
                if tp == "repo" and len(libs) > 0:
                    name = libs[0].split("/")[-1].replace(".git", "")
                    repo = {
                        "url": libs[0],
                        "repo_dir": os.path.join(
                            work_dir, libs[1] if len(libs) > 1 else name
                        ),
                    }
                    repos.append(repo)
    return repos


def console_to_str(s):
    """From pypa/pip project, pip.backwardwardcompat. License MIT."""
    try:
        return s.decode(sys.__stdout__.encoding)
    except UnicodeDecodeError:
        return s.decode("utf_8")
    except AttributeError:  # for tests, #13
        return s
