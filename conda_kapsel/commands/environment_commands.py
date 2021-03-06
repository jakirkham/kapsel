# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Copyright © 2016, Continuum Analytics, Inc. All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
# ----------------------------------------------------------------------------
"""Commands related to the environments section."""
from __future__ import absolute_import, print_function

import sys

from conda_kapsel.project import Project
from conda_kapsel import project_ops
from conda_kapsel.commands import console_utils


def _handle_status(status, success_message):
    if status:
        print(status.status_description)
        print(success_message)
        return 0
    else:
        console_utils.print_status_errors(status)
        return 1


def add_env_spec(project_dir, name, packages, channels):
    """Add an environment with packages from specified channels to the project."""
    project = Project(project_dir)
    status = project_ops.add_env_spec(project, name=name, packages=packages, channels=channels)
    return _handle_status(status, "Added environment {} to the project file.".format(name))


def remove_env_spec(project_dir, name):
    """Remove an environment with packages from the project."""
    project = Project(project_dir)
    status = project_ops.remove_env_spec(project, name=name)
    return _handle_status(status, "Removed environment {} from the project file.".format(name))


def add_packages(project, environment, packages, channels):
    """Add packages to the project."""
    project = Project(project)
    status = project_ops.add_packages(project, env_spec_name=environment, packages=packages, channels=channels)
    package_list = ", ".join(packages)
    if environment is None:
        success_message = "Added packages to project file: %s." % (package_list)
    else:
        success_message = "Added packages to environment %s in project file: %s." % (environment, package_list)
    return _handle_status(status, success_message)


def remove_packages(project, environment, packages):
    """Remove packages from the project."""
    project = Project(project)
    status = project_ops.remove_packages(project, env_spec_name=environment, packages=packages)
    package_list = ", ".join(packages)
    if environment is None:
        success_message = "Removed packages from project file: %s." % (package_list)
    else:
        success_message = "Removed packages from environment %s in project file: %s." % (environment, package_list)
    return _handle_status(status, success_message)


def list_env_specs(project_dir):
    """List environments in the project."""
    project = Project(project_dir)
    if console_utils.print_project_problems(project):
        return 1
    print("Environments for project: {}\n".format(project_dir))
    console_utils.print_names_and_descriptions(project.env_specs.values())
    return 0


def list_packages(project_dir, environment):
    """List the packages for an environment in the project."""
    project = Project(project_dir)
    if console_utils.print_project_problems(project):
        return 1
    if environment is None:
        environment = project.default_env_spec_name
    env = project.env_specs.get(environment, None)
    if env is None:
        print("Project doesn't have an environment called '{}'".format(environment), file=sys.stderr)
        return 1
    print("Packages for environment '{}':\n".format(env.name))
    print("\n".join(sorted(env.conda_packages)), end='\n\n')
    return 0


def main_add(args):
    """Start the add-environment command and return exit status code."""
    return add_env_spec(args.directory, args.name, args.packages, args.channel)


def main_remove(args):
    """Start the remove-environment command and return exit status code."""
    return remove_env_spec(args.directory, args.name)


def main_add_packages(args):
    """Start the add-packages command and return exit status code."""
    return add_packages(args.directory, args.env_spec, args.packages, args.channel)


def main_remove_packages(args):
    """Start the remove-packages command and return exit status code."""
    return remove_packages(args.directory, args.env_spec, args.packages)


def main_list_env_specs(args):
    """Start the list environments command and return exit status code."""
    return list_env_specs(args.directory)


def main_list_packages(args):
    """Start the list packages command and return exit status code."""
    return list_packages(args.directory, args.env_spec)
