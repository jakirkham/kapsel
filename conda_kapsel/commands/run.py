# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Copyright © 2016, Continuum Analytics, Inc. All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
# ----------------------------------------------------------------------------
"""The ``run`` command executes a project, by default without asking questions (fails on missing config)."""
from __future__ import absolute_import, print_function

import sys

from conda_kapsel.commands.prepare_with_mode import prepare_with_ui_mode_printing_errors
from conda_kapsel.project import Project
from conda_kapsel.project_commands import ProjectCommand


def _command_from_name(project, command_name):
    command = project.command_for_name(command_name)
    if command is None and command_name is not None:
        # if the command name isn't a configured command name,
        # interpret the command as a notebook or executable.
        attrs = dict(env_spec=project.default_env_spec_name)
        if command_name.lower().endswith(".ipynb"):
            attrs['notebook'] = command_name
        else:
            attrs['args'] = [command_name]

        command = ProjectCommand(name=command_name, attributes=attrs)

    return command


def run_command(project_dir, ui_mode, conda_environment, command_name, extra_command_args):
    """Run the project.

    Returns:
        Does not return if successful.
    """
    project = Project(project_dir)
    environ = None

    command = _command_from_name(project, command_name)

    result = prepare_with_ui_mode_printing_errors(project,
                                                  ui_mode=ui_mode,
                                                  env_spec_name=conda_environment,
                                                  command=command,
                                                  extra_command_args=extra_command_args,
                                                  environ=environ)

    if result.failed:
        # errors were printed already
        return
    elif result.command_exec_info is None:
        print("No known run command for project %s; try adding a 'commands:' section to kapsel.yml" % project_dir,
              file=sys.stderr)
    else:
        try:
            result.command_exec_info.execvpe()
        except OSError as e:
            print("Failed to execute '%s': %s" % (" ".join(result.command_exec_info.args), e.strerror), file=sys.stderr)


def main(args):
    """Start the run command and return exit status code.."""
    run_command(args.directory, args.mode, args.env_spec, args.command, args.extra_args_for_command)
    # if we returned, we failed to run the command and should have printed an error
    return 1
