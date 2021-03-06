# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Copyright © 2016, Continuum Analytics, Inc. All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
# ----------------------------------------------------------------------------
"""The ``upload`` command makes an archive of the project."""
from __future__ import absolute_import, print_function

from conda_kapsel.project import Project
from conda_kapsel.commands import console_utils
import conda_kapsel.project_ops as project_ops


def upload_command(project_dir, site, username, token):
    """Upload project to Anaconda.

    Returns:
        exit code
    """
    project = Project(project_dir)
    status = project_ops.upload(project, site=site, username=username, token=token)
    if status:
        for line in status.logs:
            print(line)
        print(status.status_description)
        return 0
    else:
        console_utils.print_status_errors(status)
        return 1


def main(args):
    """Start the upload command and return exit status code."""
    return upload_command(args.directory, args.site, args.user, args.token)
