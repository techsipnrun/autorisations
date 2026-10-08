"""python -m tests [labels...] : point d'entrée utilisant les paramètres de test."""
import os
import sys

from django.core.management import execute_from_command_line

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"
arguments = sys.argv[1:]
if not arguments or arguments[0].startswith("-"):
    arguments.insert(0, "tests")
execute_from_command_line(["manage.py", "test", *arguments])
