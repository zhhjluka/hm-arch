"""PyInstaller entry point for the ``hm-arch`` standalone executable."""

from hm_arch.integrations.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
