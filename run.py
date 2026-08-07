#!/usr/bin/env python3
"""Nimble Lab Manager -- one-command launcher.

Ensures a local virtual environment exists, installs dependencies into it if
needed, then launches the FastAPI app with uvicorn. Cross-platform.

Usage:
    python3 run.py
"""

import os
import shutil
import subprocess
import sys
import venv

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(REPO_ROOT, ".venv")
REQUIREMENTS = os.path.join(REPO_ROOT, "requirements.txt")

HOST = "127.0.0.1"
PORT = 8770
URL = f"http://{HOST}:{PORT}"


def venv_python(venv_dir):
    """Return the path to the python executable inside a venv."""
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _pip_works(python_exe, extra=()):
    """Return True if `python_exe -m pip [extra] --version` succeeds."""
    return (
        subprocess.run(
            [python_exe, "-m", "pip", *extra, "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def ensurepip_available():
    """Return True if the launching interpreter can bootstrap pip via ensurepip.

    Some minimal Linux/WSL Python installs ship without the ensurepip module,
    which makes `venv.EnvBuilder(with_pip=True)` fail. Detect that up front so we
    can create the venv without pip and bootstrap dependencies another way.
    """
    return (
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def ensure_venv():
    """Create the local venv if it does not already exist.

    Prefers a venv with its own pip. On hosts where ensurepip is missing, falls
    back to a pip-less venv (dependencies get installed via the host pip in
    install_requirements).
    """
    py = venv_python(VENV_DIR)
    if os.path.exists(py):
        return py
    print(f"Creating virtual environment at {VENV_DIR} ...")
    with_pip = ensurepip_available()
    if not with_pip:
        print("  (ensurepip unavailable on this host; using host pip instead)")
    venv.EnvBuilder(with_pip=with_pip).create(VENV_DIR)
    py = venv_python(VENV_DIR)
    if not os.path.exists(py):
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        sys.exit(f"Failed to create virtual environment at {VENV_DIR}")
    return py


def deps_installed(py):
    """Return True if the venv can import every third-party module the app needs
    at startup. Checking more than just fastapi means adding a new dependency to
    requirements.txt triggers a reinstall on an existing venv instead of the
    server crashing on a missing import."""
    result = subprocess.run(
        [py, "-c", "import fastapi, uvicorn, segno, multipart"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def install_requirements(py):
    """Install requirements.txt into the venv.

    Uses the venv's own pip when present. On pip-less venvs (ensurepip-missing
    hosts) it bridges through the launching interpreter's pip with the --python
    flag, which installs straight into the target venv's site-packages.
    """
    print("Installing dependencies (this only happens once) ...")
    if _pip_works(py):
        subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([py, "-m", "pip", "install", "-r", REQUIREMENTS])
    elif _pip_works(sys.executable, extra=["--python", py]):
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--python", py, "install", "-r", REQUIREMENTS]
        )
    else:
        sys.exit(
            "No usable pip found to install dependencies.\n"
            f"Install pip for {sys.executable} (e.g. 'sudo apt install python3-pip'\n"
            "or 'python3 -m ensurepip --upgrade') and re-run python3 run.py."
        )


def main():
    py = ensure_venv()

    if not deps_installed(py):
        install_requirements(py)

    print()
    print("=" * 52)
    print("  Nimble Lab Manager is starting.")
    print(f"  Open your browser to:  {URL}")
    print("  Press Ctrl+C to stop.")
    print("=" * 52)
    print()

    cmd = [
        py,
        "-m",
        "uvicorn",
        "app.server:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]
    # This one-command launcher is the portfolio/demo entry point, so seed the
    # demo lab and the demo logins unless the operator has chosen otherwise.
    # (A deployed instance -- Docker/Fly -- leaves this unset and starts empty.)
    env = os.environ.copy()
    env.setdefault("NLM_SEED_DEMO", "1")
    try:
        subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    except KeyboardInterrupt:
        print("\nShutting down. Goodbye.")


if __name__ == "__main__":
    main()
