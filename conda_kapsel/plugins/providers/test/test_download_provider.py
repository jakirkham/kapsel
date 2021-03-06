# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Copyright © 2016, Continuum Analytics, Inc. All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
# ----------------------------------------------------------------------------
from __future__ import absolute_import

import codecs
import os
import shutil
import zipfile

from conda_kapsel.test.project_utils import project_no_dedicated_env
from conda_kapsel.internal.test.tmpfile_utils import (with_directory_contents, with_tmp_zipfile)
from conda_kapsel.test.environ_utils import minimal_environ, strip_environ
from conda_kapsel.internal.test.http_utils import http_get_async, http_post_async
from conda_kapsel.local_state_file import DEFAULT_LOCAL_STATE_FILENAME
from conda_kapsel.local_state_file import LocalStateFile
from conda_kapsel.plugins.registry import PluginRegistry
from conda_kapsel.plugins.requirement import UserConfigOverrides
from conda_kapsel.plugins.providers.download import DownloadProvider
from conda_kapsel.plugins.requirements.download import DownloadRequirement
from conda_kapsel.prepare import (prepare_without_interaction, prepare_with_browser_ui, unprepare)
from conda_kapsel import provide
from conda_kapsel.project_file import DEFAULT_PROJECT_FILENAME

from tornado import gen

DATAFILE_CONTENT = ("downloads:\n"
                    "    DATAFILE:\n"
                    "        url: http://localhost/data.csv\n"
                    "        md5: 12345abcdef\n"
                    "        filename: data.csv\n")

ZIPPED_DATAFILE_CONTENT = ("downloads:\n"
                           "    DATAFILE:\n"
                           "        url: http://localhost/data.zip\n"
                           "        filename: data\n")

ZIPPED_DATAFILE_CONTENT_CHECKSUM = (ZIPPED_DATAFILE_CONTENT + "        md5: 12345abcdef\n")

ZIPPED_DATAFILE_CONTENT_NO_UNZIP = (ZIPPED_DATAFILE_CONTENT + "        unzip: false\n")

# have to specify unzip:true manually here
ZIPPED_DATAFILE_CONTENT_NO_ZIP_SUFFIX = ("downloads:\n"
                                         "    DATAFILE:\n"
                                         "        url: http://localhost/data\n"
                                         "        unzip: true\n"
                                         "        filename: data\n")


def _download_requirement():
    return DownloadRequirement(registry=PluginRegistry(),
                               env_var="DATAFILE",
                               url='http://localhost/data.csv',
                               filename='data.csv')


def test_prepare_and_unprepare_download(monkeypatch):
    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            with open(os.path.join(dirname, 'data.csv'), 'w') as out:
                out.write('data')
            self._hash = '12345abcdef'
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)
        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ
        filename = os.path.join(dirname, 'data.csv')
        assert os.path.exists(filename)

        status = unprepare(project, result)
        assert status.logs == ["Removed downloaded file %s." % filename,
                               ("Current environment is not in %s, no need to delete it." % dirname)]
        assert status.status_description == 'Success.'
        assert status
        assert not os.path.exists(filename)

    with_directory_contents({DEFAULT_PROJECT_FILENAME: DATAFILE_CONTENT}, provide_download)


def test_prepare_download_mismatched_checksum_after_download(monkeypatch):
    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            with open(os.path.join(dirname, 'data.csv'), 'w') as out:
                out.write('data')
            self._hash = 'mismatched'
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)

        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert not result
        assert ('Error downloading http://localhost/data.csv: mismatched hashes. '
                'Expected: 12345abcdef, calculated: mismatched') in result.errors

    with_directory_contents({DEFAULT_PROJECT_FILENAME: DATAFILE_CONTENT}, provide_download)


def test_prepare_download_exception(monkeypatch):
    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            raise Exception('error')

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)
        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert not result
        assert ('missing requirement to run this project: A downloaded file which is referenced by DATAFILE.'
                ) in result.errors

        status = unprepare(project, result)
        filename = os.path.join(dirname, 'data.csv')
        assert status.logs == ["No need to remove %s which wasn't downloaded." % filename,
                               ("Current environment is not in %s, no need to delete it." % dirname)]
        assert status.status_description == 'Success.'

    with_directory_contents({DEFAULT_PROJECT_FILENAME: DATAFILE_CONTENT}, provide_download)


def test_unprepare_download_fails(monkeypatch):
    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            with open(os.path.join(dirname, 'data.csv'), 'w') as out:
                out.write('data')
            self._hash = '12345abcdef'
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)
        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ
        filename = os.path.join(dirname, 'data.csv')
        assert os.path.exists(filename)

        def mock_remove(path):
            raise IOError("Not gonna remove this")

        monkeypatch.setattr("os.remove", mock_remove)

        status = unprepare(project, result)
        assert status.logs == []
        assert status.status_description == ('Failed to remove %s: Not gonna remove this.' % filename)
        assert status.errors == []
        assert not status
        assert os.path.exists(filename)

        monkeypatch.undo()  # so os.remove isn't broken during directory cleanup

    with_directory_contents({DEFAULT_PROJECT_FILENAME: DATAFILE_CONTENT}, provide_download)


def test_provide_minimal(monkeypatch):
    MIN_DATAFILE_CONTENT = ("downloads:\n" "    DATAFILE: http://localhost/data.csv\n")

    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            with open(os.path.join(dirname, 'data.csv'), 'w') as out:
                out.write('data')
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)
        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ

    with_directory_contents({DEFAULT_PROJECT_FILENAME: MIN_DATAFILE_CONTENT}, provide_download)


def test_provide_no_download_in_check_mode(monkeypatch):
    MIN_DATAFILE_CONTENT = ("downloads:\n" "    DATAFILE: http://localhost/data.csv\n")

    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            raise Exception("should not have tried to download in check mode")

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)

        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project,
                                             environ=minimal_environ(PROJECT_DIR=dirname),
                                             mode=provide.PROVIDE_MODE_CHECK)
        assert not result

    with_directory_contents({DEFAULT_PROJECT_FILENAME: MIN_DATAFILE_CONTENT}, provide_download)


def test_provide_missing_url(monkeypatch):
    ERR_DATAFILE_CONTENT = ("downloads:\n" "    DATAFILE:\n" "       filename: data.csv\n")

    def provide_download(dirname):
        project = project_no_dedicated_env(dirname)
        prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert "Download item DATAFILE doesn't contain a 'url' field." in project.problems

    with_directory_contents({DEFAULT_PROJECT_FILENAME: ERR_DATAFILE_CONTENT}, provide_download)


def test_provide_empty_url(monkeypatch):
    ERR_DATAFILE_CONTENT = ("downloads:\n" "    DATAFILE:\n" "       url: \"\"\n")

    def provide_download(dirname):
        project = project_no_dedicated_env(dirname)
        prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert "Download item DATAFILE has an empty 'url' field." in project.problems

    with_directory_contents({DEFAULT_PROJECT_FILENAME: ERR_DATAFILE_CONTENT}, provide_download)


def test_provide_multiple_checksums(monkeypatch):
    ERR_DATAFILE_CONTENT = ("downloads:\n"
                            "    DATAFILE:\n"
                            "       url: http://localhost/\n"
                            "       md5: abcdefg\n"
                            "       sha1: abcdefg\n")

    def provide_download(dirname):
        project = project_no_dedicated_env(dirname)
        prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert "Multiple checksums for download DATAFILE: md5 and sha1." in project.problems

    with_directory_contents({DEFAULT_PROJECT_FILENAME: ERR_DATAFILE_CONTENT}, provide_download)


def test_provide_wrong_form(monkeypatch):
    ERR_DATAFILE_CONTENT = ("downloads:\n" "    - http://localhost/data.csv\n")

    def provide_download(dirname):
        project = project_no_dedicated_env(dirname)
        prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert ("%s: 'downloads:' section should be a dictionary, found ['http://localhost/data.csv']" % os.path.join(
            dirname, DEFAULT_PROJECT_FILENAME)) in project.problems

    with_directory_contents({DEFAULT_PROJECT_FILENAME: ERR_DATAFILE_CONTENT}, provide_download)


def test_failed_download(monkeypatch):
    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 400
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)
        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert not result
        assert ('missing requirement to run this project: A downloaded file which is referenced by DATAFILE.'
                ) in result.errors

    with_directory_contents({DEFAULT_PROJECT_FILENAME: DATAFILE_CONTENT}, provide_download)


def test_failed_download_before_connect(monkeypatch):
    def provide_download(dirname):
        @gen.coroutine
        def mock_downloader_run(self, loop):
            # if we don't even get an HTTP response, the errors are handled this way,
            # e.g. if the URL is bad.
            self._errors = ['This went horribly wrong']
            raise gen.Return(None)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)
        project = project_no_dedicated_env(dirname)
        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert not result
        assert ('missing requirement to run this project: A downloaded file which is referenced by DATAFILE.'
                ) in result.errors

    with_directory_contents({DEFAULT_PROJECT_FILENAME: DATAFILE_CONTENT}, provide_download)


def test_file_exists(monkeypatch):
    def provide_download(dirname):
        FILENAME = os.path.join(dirname, 'data.csv')
        requirement = _download_requirement()
        local_state_file = LocalStateFile.load_for_directory(dirname)
        local_state_file.set_service_run_state(requirement.env_var, {'filename': FILENAME})
        local_state_file.save()
        with open(FILENAME, 'w') as out:
            out.write('data')
        project = project_no_dedicated_env(dirname)

        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ

    LOCAL_STATE = ("DATAFILE:\n" "  filename: data.csv")

    with_directory_contents(
        {
            DEFAULT_PROJECT_FILENAME: DATAFILE_CONTENT,
            DEFAULT_LOCAL_STATE_FILENAME: LOCAL_STATE
        }, provide_download)


def test_prepare_download_of_zip_file(monkeypatch):
    def provide_download_of_zip(zipname, dirname):
        with codecs.open(os.path.join(dirname, DEFAULT_PROJECT_FILENAME), 'w', 'utf-8') as f:
            f.write(ZIPPED_DATAFILE_CONTENT)

        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            assert self._url.endswith(".zip")
            assert self._filename.endswith(".zip")
            shutil.copyfile(zipname, self._filename)
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)

        project = project_no_dedicated_env(dirname)

        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ
        assert os.path.isdir(os.path.join(dirname, 'data'))
        assert os.path.isfile(os.path.join(dirname, 'data', 'foo'))
        assert codecs.open(os.path.join(dirname, 'data', 'foo')).read() == 'hello\n'

    with_tmp_zipfile(dict(foo='hello\n'), provide_download_of_zip)


def test_prepare_download_of_zip_file_checksum(monkeypatch):
    def provide_download_of_zip(zipname, dirname):
        with codecs.open(os.path.join(dirname, DEFAULT_PROJECT_FILENAME), 'w', 'utf-8') as f:
            f.write(ZIPPED_DATAFILE_CONTENT_CHECKSUM)

        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            assert self._url.endswith(".zip")
            assert self._filename.endswith(".zip")
            shutil.copyfile(zipname, self._filename)
            self._hash = '12345abcdef'
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)
        project = project_no_dedicated_env(dirname)

        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ
        assert os.path.isdir(os.path.join(dirname, 'data'))
        assert os.path.isfile(os.path.join(dirname, 'data', 'foo'))
        assert codecs.open(os.path.join(dirname, 'data', 'foo')).read() == 'hello\n'

        status = unprepare(project, result)
        filename = os.path.join(dirname, 'data')
        assert status.logs == ["Removed downloaded file %s." % filename,
                               ("Current environment is not in %s, no need to delete it." % dirname)]
        assert status.status_description == "Success."

    with_tmp_zipfile(dict(foo='hello\n'), provide_download_of_zip)


def test_prepare_download_of_zip_file_no_unzip(monkeypatch):
    def provide_download_of_zip_no_unzip(zipname, dirname):
        with codecs.open(os.path.join(dirname, DEFAULT_PROJECT_FILENAME), 'w', 'utf-8') as f:
            f.write(ZIPPED_DATAFILE_CONTENT_NO_UNZIP)

        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            assert self._url.endswith(".zip")
            # we aren't going to unzip so we should be downloading straignt to
            # the specified filename 'data' without the .zip on it
            assert not self._filename.endswith(".zip")
            shutil.copyfile(zipname, self._filename)
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)

        project = project_no_dedicated_env(dirname)

        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ
        assert os.path.isfile(os.path.join(dirname, 'data'))
        with zipfile.ZipFile(os.path.join(dirname, 'data')) as zf:
            assert zf.namelist() == ['foo']

    with_tmp_zipfile(dict(foo='hello\n'), provide_download_of_zip_no_unzip)


def test_prepare_download_of_zip_file_no_zip_extension(monkeypatch):
    def provide_download_of_zip(zipname, dirname):
        with codecs.open(os.path.join(dirname, DEFAULT_PROJECT_FILENAME), 'w', 'utf-8') as f:
            f.write(ZIPPED_DATAFILE_CONTENT_NO_ZIP_SUFFIX)

        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            # we add .zip to the download filename, even though it wasn't in the URL
            assert not self._url.endswith(".zip")
            assert self._filename.endswith(".zip")
            shutil.copyfile(zipname, self._filename)
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)

        project = project_no_dedicated_env(dirname)

        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert hasattr(result, 'environ')
        assert 'DATAFILE' in result.environ
        assert os.path.isdir(os.path.join(dirname, 'data'))
        assert os.path.isfile(os.path.join(dirname, 'data', 'foo'))
        assert codecs.open(os.path.join(dirname, 'data', 'foo')).read() == 'hello\n'

    with_tmp_zipfile(dict(foo='hello\n'), provide_download_of_zip)


def test_prepare_download_of_broken_zip_file(monkeypatch):
    def provide_download_of_zip(dirname):
        with codecs.open(os.path.join(dirname, DEFAULT_PROJECT_FILENAME), 'w', 'utf-8') as f:
            f.write(ZIPPED_DATAFILE_CONTENT)

        @gen.coroutine
        def mock_downloader_run(self, loop):
            class Res:
                pass

            res = Res()
            res.code = 200
            assert self._url.endswith(".zip")
            assert self._filename.endswith(".zip")
            with codecs.open(self._filename, 'w', 'utf-8') as f:
                f.write("This is not a zip file.")
            raise gen.Return(res)

        monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)

        project = project_no_dedicated_env(dirname)

        result = prepare_without_interaction(project, environ=minimal_environ(PROJECT_DIR=dirname))
        assert not result
        assert [("Failed to unzip %s: File is not a zip file" % os.path.join(dirname, "data.zip")),
                "missing requirement to run this project: A downloaded file which is referenced by DATAFILE.",
                "  Environment variable DATAFILE is not set."] == result.errors

    with_directory_contents(dict(), provide_download_of_zip)


def test_config_html(monkeypatch):
    def config_html(dirname):
        FILENAME = os.path.join(dirname, 'data.csv')
        local_state_file = LocalStateFile.load_for_directory(dirname)
        requirement = _download_requirement()
        environ = minimal_environ(PROJECT_DIR=dirname)
        status = requirement.check_status(environ, local_state_file, 'default', UserConfigOverrides())
        provider = DownloadProvider()
        html = provider.config_html(requirement, environ, local_state_file, UserConfigOverrides(), status)
        assert 'Download {} to {}'.format(requirement.url, requirement.filename) in html

        with open(FILENAME, 'w') as f:
            f.write('boo')

        env = minimal_environ(PROJECT_DIR=dirname)
        status = requirement.check_status(env, local_state_file, 'default', UserConfigOverrides())
        html = provider.config_html(requirement, env, local_state_file, UserConfigOverrides(), status)
        expected_choice = 'Use already-downloaded file {}'.format(FILENAME)
        assert expected_choice in html

    with_directory_contents({DEFAULT_LOCAL_STATE_FILENAME: DATAFILE_CONTENT}, config_html)


def _run_browser_ui_test(monkeypatch, directory_contents, initial_environ, http_actions, final_result_check):
    @gen.coroutine
    def mock_downloader_run(self, loop):
        class Res:
            pass

        res = Res()
        if self._url.endswith("?error=true"):
            res.code = 400
        else:
            with open(self._filename, 'w') as f:
                f.write("boo")

            res.code = 200
        raise gen.Return(res)

    monkeypatch.setattr("conda_kapsel.internal.http_client.FileDownloader.run", mock_downloader_run)

    replaced = dict()
    for key, value in directory_contents.items():
        replaced[key] = value.format(url="http://example.com/bar", error_url="http://example.com/bar?error=true")
    directory_contents = replaced

    from tornado.ioloop import IOLoop
    io_loop = IOLoop(make_current=False)

    http_done = dict()

    def mock_open_new_tab(url):
        @gen.coroutine
        def do_http():
            try:
                for action in http_actions:
                    yield action(url)
            except Exception as e:
                http_done['exception'] = e

            http_done['done'] = True

            io_loop.stop()
            io_loop.close()

        io_loop.add_callback(do_http)

    monkeypatch.setattr('webbrowser.open_new_tab', mock_open_new_tab)

    def do_browser_ui_test(dirname):
        project = project_no_dedicated_env(dirname)
        assert [] == project.problems
        if not isinstance(initial_environ, dict):
            environ = initial_environ(dirname)
        else:
            environ = initial_environ
        result = prepare_with_browser_ui(project, environ=environ, io_loop=io_loop, keep_going_until_success=True)

        # finish up the last http action if prepare_ui.py stopped the loop before we did
        while 'done' not in http_done:
            io_loop.call_later(0.01, lambda: io_loop.stop())
            io_loop.start()

        if 'exception' in http_done:
            raise http_done['exception']

        final_result_check(dirname, result)

    with_directory_contents(directory_contents, do_browser_ui_test)


def _extract_radio_items(response, provider='DownloadProvider'):
    from conda_kapsel.internal.plugin_html import _BEAUTIFUL_SOUP_BACKEND
    from bs4 import BeautifulSoup

    if response.code != 200:
        raise Exception("got a bad http response " + repr(response))

    soup = BeautifulSoup(response.body, _BEAUTIFUL_SOUP_BACKEND)
    radios = soup.find_all("input", attrs={'type': 'radio'})
    return [r for r in radios if (provider in r['name'])]


def _form_names(response, provider='DownloadProvider'):
    from conda_kapsel.internal.plugin_html import _BEAUTIFUL_SOUP_BACKEND
    from bs4 import BeautifulSoup

    if response.code != 200:
        raise Exception("got a bad http response " + repr(response))

    soup = BeautifulSoup(response.body, _BEAUTIFUL_SOUP_BACKEND)
    named_elements = soup.find_all(attrs={'name': True})
    names = set()
    for element in named_elements:
        if provider in element['name']:
            names.add(element['name'])
    return names


def _prefix_form(form_names, form):
    prefixed = dict()
    for (key, value) in form.items():
        found = False
        for name in form_names:
            if name.endswith("." + key):
                prefixed[name] = value
                found = True
                break
        if not found:
            raise RuntimeError("Form field %s in %r could not be prefixed from %r" % (key, form, form_names))
    return prefixed


def _verify_choices(response, expected):
    name = None
    radios = _extract_radio_items(response)
    actual = []
    for r in radios:
        actual.append((r['value'], 'checked' in r.attrs))
    assert expected == tuple(actual)
    return name


@gen.coroutine
def post_choose_inherited_env(url):
    response = yield http_get_async(url)
    assert response.code == 200
    body = response.body.decode('utf-8')
    assert 'activated environment' in body
    form_names = _form_names(response, provider='CondaEnvProvider')
    form = _prefix_form(form_names, {'source': 'inherited'})
    response = yield http_post_async(url, form=form)
    assert response.code == 200


def test_browser_ui_with_no_env_var_set(monkeypatch):
    directory_contents = {DEFAULT_PROJECT_FILENAME: """
downloads:
  MYDOWNLOAD:
    url: {url}
    """}
    initial_environ = minimal_environ()

    @gen.coroutine
    def get_initial(url):
        response = yield http_get_async(url)
        assert response.code == 200
        body = response.body.decode('utf-8')
        assert "Download {} to {}".format('http://example.com/bar', 'bar') in body
        _verify_choices(response,
                        (
                            # by default, perform the download
                            ('download', True),
                            # allow typing in a manual value
                            ('variables', False)))

    @gen.coroutine
    def post_empty_form(url):
        response = yield http_post_async(url, body='')
        assert response.code == 200
        body = response.body.decode('utf-8')
        assert "Done!" in body
        assert "File downloaded to " in body
        _verify_choices(response, ())

    def final_result_check(dirname, result):
        assert result
        expected = dict(MYDOWNLOAD=os.path.join(dirname, 'bar'), PROJECT_DIR=dirname)
        assert expected == strip_environ(result.environ)

    _run_browser_ui_test(monkeypatch=monkeypatch,
                         directory_contents=directory_contents,
                         initial_environ=initial_environ,
                         http_actions=[post_choose_inherited_env, get_initial, post_empty_form],
                         final_result_check=final_result_check)


def test_browser_ui_with_env_var_already_set(monkeypatch):
    directory_contents = {DEFAULT_PROJECT_FILENAME: """
downloads:
  MYDOWNLOAD:
    url: {url}
    """,
                          'existing_data': 'boo'}

    def initial_environ(dirname):
        return minimal_environ(MYDOWNLOAD=os.path.join(dirname, 'existing_data'))

    @gen.coroutine
    def get_initial(url):
        response = yield http_get_async(url)
        assert response.code == 200
        body = response.body.decode('utf-8')
        assert "Download {} to {}".format('http://example.com/bar', 'bar') in body
        _verify_choices(response,
                        (
                            # by default, do not perform the download
                            ('download', False),
                            # by default, keep existing value
                            ('environ', True),
                            # allow typing in a manual value
                            ('variables', False)))

    @gen.coroutine
    def post_empty_form(url):
        response = yield http_post_async(url, body='')
        assert response.code == 200
        body = response.body.decode('utf-8')
        assert "Done!" in body
        assert "File downloaded to " in body
        _verify_choices(response, ())

    def final_result_check(dirname, result):
        assert result
        expected = dict(MYDOWNLOAD=os.path.join(dirname, 'existing_data'), PROJECT_DIR=dirname)
        assert expected == strip_environ(result.environ)

    _run_browser_ui_test(monkeypatch=monkeypatch,
                         directory_contents=directory_contents,
                         initial_environ=initial_environ,
                         http_actions=[post_choose_inherited_env, get_initial, post_empty_form],
                         final_result_check=final_result_check)


def test_browser_ui_shows_download_error(monkeypatch):
    directory_contents = {DEFAULT_PROJECT_FILENAME: """
downloads:
  MYDOWNLOAD:
    url: {error_url}
    """}
    initial_environ = minimal_environ()

    @gen.coroutine
    def get_initial(url):
        response = yield http_get_async(url)
        assert response.code == 200
        body = response.body.decode('utf-8')
        assert "Download {} to {}".format('http://example.com/bar?error=true', 'bar') in body
        _verify_choices(response,
                        (
                            # by default, perform the download
                            ('download', True),
                            # allow typing in a manual value
                            ('variables', False)))

    @gen.coroutine
    def post_empty_form(url):
        response = yield http_post_async(url, body='')
        assert response.code == 200
        body = response.body.decode('utf-8')
        # TODO: we are not currently showing the error, but the fix is over in UIServer
        # and not related to DownloadProvider per se, so for now this test checks for
        # what happens (you just see the option to try again) instead of what should happen
        # (it should also display the error message)
        assert "Download {} to {}".format('http://example.com/bar?error=true', 'bar') in body
        _verify_choices(response,
                        (
                            # by default, perform the download
                            ('download', True),
                            # allow typing in a manual value
                            ('variables', False)))

    def final_result_check(dirname, result):
        assert not result

    _run_browser_ui_test(monkeypatch=monkeypatch,
                         directory_contents=directory_contents,
                         initial_environ=initial_environ,
                         http_actions=[post_choose_inherited_env, get_initial, post_empty_form],
                         final_result_check=final_result_check)


def test_browser_ui_choose_download_then_manual_override(monkeypatch):
    directory_contents = {DEFAULT_PROJECT_FILENAME: """
variables:
  # this keeps the prepare from ever ending
  - FOO

downloads:
  MYDOWNLOAD:
    url: {url}
    """,
                          'existing_data': 'boo'}
    capture_dirname = dict()

    def initial_environ(dirname):
        capture_dirname['value'] = dirname
        return minimal_environ(MYDOWNLOAD=os.path.join(dirname, 'existing_data'))

    stuff = dict()

    @gen.coroutine
    def get_initial(url):
        response = yield http_get_async(url)
        assert response.code == 200
        body = response.body.decode('utf-8')
        stuff['form_names'] = _form_names(response)
        assert "Download {} to {}".format('http://example.com/bar', 'bar') in body
        _verify_choices(response,
                        (
                            # offer to perform the download but by default use the preset env var
                            ('download', False),
                            # by default, keep env var
                            ('environ', True),
                            # allow typing in a manual value
                            ('variables', False)))

    @gen.coroutine
    def post_do_download(url):
        form = _prefix_form(stuff['form_names'], {'source': 'download'})
        response = yield http_post_async(url, form=form)
        assert response.code == 200
        body = response.body.decode('utf-8')
        assert 'Keep value' in body
        stuff['form_names'] = _form_names(response)
        _verify_choices(response,
                        (
                            # the download caused env var to be set, offer to keep it
                            ('environ', True),
                            # allow typing in a manual value
                            ('variables', False)))

    @gen.coroutine
    def post_use_env(url):
        dirname = capture_dirname['value']
        form = _prefix_form(stuff['form_names'], {'source': 'variables',
                                                  'value': os.path.join(dirname, 'existing_data')})
        response = yield http_post_async(url, form=form)
        assert response.code == 200
        body = response.body.decode('utf-8')
        assert 'Use this' in body
        _verify_choices(response,
                        (('download', False),
                         ('environ', False),
                         # we've switched to the override value
                         ('variables', True)))

    def final_result_check(dirname, result):
        assert not result  # because 'FOO' isn't set

    _run_browser_ui_test(monkeypatch=monkeypatch,
                         directory_contents=directory_contents,
                         initial_environ=initial_environ,
                         http_actions=[post_choose_inherited_env, get_initial, post_do_download, post_use_env],
                         final_result_check=final_result_check)
