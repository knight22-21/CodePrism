"""Intentionally insecure — used only in detector tests."""

import os
import subprocess


def run_expr(user_input: str):
    return eval(user_input)


def search(cursor, name: str):
    cursor.execute("SELECT * FROM users WHERE name = '" + name + "'")


def search_fmt(cursor, table: str):
    cursor.execute(f"SELECT * FROM {table}")


def run_cmd(cmd: str) -> None:
    subprocess.run(cmd, shell=True)
