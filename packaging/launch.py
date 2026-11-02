"""Entry point for the Windows build (PyInstaller).

  dupefinder.exe                starts the app
  dupefinder.exe --smoke-test   checks the build works, exit code 0 = OK
"""
import sys

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        from dupefinder.app import smoke
        sys.exit(smoke.run())
    from dupefinder.app.window import run
    sys.exit(run())
