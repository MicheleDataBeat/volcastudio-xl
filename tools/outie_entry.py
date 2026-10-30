"""Frozen desktop entry point; never starts a console UI."""
from volcastudio.outie import main

if __name__ == '__main__':
    raise SystemExit(main())
