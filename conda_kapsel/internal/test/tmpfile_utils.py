# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Copyright © 2016, Continuum Analytics, Inc. All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
# ----------------------------------------------------------------------------
from __future__ import print_function, absolute_import

import codecs
import tempfile
import shutil
import os
import sys
import zipfile

from conda_kapsel.internal.makedirs import makedirs_ok_if_exists
from conda_kapsel.local_state_file import LocalStateFile

local_tmp = os.path.abspath("./build/tmp")
makedirs_ok_if_exists(local_tmp)


class TmpDir(object):
    def __init__(self, prefix):
        self._dir = tempfile.mkdtemp(prefix=prefix, dir=local_tmp)

    def __exit__(self, type, value, traceback):
        try:
            shutil.rmtree(path=self._dir)
        except Exception as e:
            # prefer original exception to rmtree exception
            if value is None:
                print("Exception cleaning up TmpDir %s: %s" % (self._dir, str(e)), file=sys.stderr)
                raise e
            else:
                print("Failed to clean up TmpDir %s: %s" % (self._dir, str(e)), file=sys.stderr)
                raise value

    def __enter__(self):
        return self._dir


def with_directory_contents(contents, func):
    with (TmpDir(prefix="test-")) as dirname:
        for filename, file_content in contents.items():
            path = os.path.join(dirname, filename)
            if file_content is None:
                # make a directory
                makedirs_ok_if_exists(path)
            else:
                makedirs_ok_if_exists(os.path.dirname(path))
                with codecs.open(path, 'w', 'utf-8') as f:
                    f.write(file_content)
        return func(os.path.realpath(dirname))


def with_temporary_file(func, dir=None):
    if dir is None:
        dir = local_tmp
    import tempfile
    # Windows throws a permission denied if we use delete=True for
    # auto-delete, and then try to open the file again ourselves
    # with f.name. So we manually delete in the finally block
    # below.
    f = tempfile.NamedTemporaryFile(dir=dir, delete=False)
    try:
        return func(f)
    finally:
        f.close()
        os.remove(f.name)


def with_file_contents(contents, func, dir=None):
    def with_file_object(f):
        f.write(contents.encode("UTF-8"))
        f.flush()
        # Windows will get mad if we try to rename it without closing,
        # and some users of with_file_contents want to rename it.
        f.close()
        return func(f.name)

    return with_temporary_file(with_file_object, dir=dir)


def with_temporary_script_commandline(contents, func, dir=None):
    def script_wrapper(filename):
        return func(['python', os.path.abspath(filename)])

    return with_file_contents(contents, script_wrapper, dir=dir)


def tmp_script_commandline(contents):
    import tempfile
    # delete=False required so windows will allow the file to be
    # opened.  (we never delete this tmpfile, except when the
    # entire tmpdir is blown away)
    f = tempfile.NamedTemporaryFile(dir=local_tmp, delete=False, suffix=".py", prefix="script_")
    f.write(contents.encode('utf-8'))
    f.close()
    return ['python', os.path.abspath(f.name)]


def tmp_local_state_file():
    import tempfile
    # delete=False required so windows will allow the file to be opened
    f = tempfile.NamedTemporaryFile(dir=local_tmp, delete=False)
    local_state = LocalStateFile(f.name)
    f.close()
    os.remove(f.name)
    return local_state


def with_tmp_zipfile(contents, f):
    """Call 'f' with a zip of 'contents' and an empty working directory name."""

    def using_temporary_file(handle):
        with zipfile.ZipFile(handle.name, 'w') as zf:
            for key, value in contents.items():
                zf.writestr(key, value.encode('utf-8'))

        def using_directory(dirname):
            return f(handle.name, dirname)

        return with_directory_contents(dict(), using_directory)

    return with_temporary_file(using_temporary_file)
