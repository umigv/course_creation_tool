#!/usr/bin/env python3
"""Run Tk dialogs outside the Pygame/SDL process."""

import argparse
import json
import sys


def _create_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    return root


def _select_folder(root, title, initial_dir):
    from tkinter import filedialog

    options = {"parent": root, "title": title, "mustexist": True}
    if initial_dir:
        options["initialdir"] = initial_dir
    folder = filedialog.askdirectory(**options)
    print(json.dumps(folder or None))


def _show_error(root, title, message):
    from tkinter import messagebox

    messagebox.showerror(title=title, message=message, parent=root)


def main():
    parser = argparse.ArgumentParser(description="Tk dialog helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    folder_parser = subparsers.add_parser("folder")
    folder_parser.add_argument("--title", required=True)
    folder_parser.add_argument("--initial-dir")

    error_parser = subparsers.add_parser("error")
    error_parser.add_argument("--title", required=True)
    error_parser.add_argument("--message", required=True)

    args = parser.parse_args()
    root = None
    try:
        root = _create_root()
        if args.command == "folder":
            _select_folder(root, args.title, args.initial_dir)
        else:
            _show_error(root, args.title, args.message)
        return 0
    except Exception as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
