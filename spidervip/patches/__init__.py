"""Receiver patches — install / remove / status of on-box add-ons from the Console.

Files live under ``/data`` and start from the vendor boot hook
``/home/gx/local/user_script``; a firmware update or a factory reset removes
them, so the Console page ``/patches/`` shows what is installed and puts it
back with one click. See ``docs/patches/README.md``.
"""
