# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# Copyright © 2016, Continuum Analytics, Inc. All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
# ----------------------------------------------------------------------------
from __future__ import absolute_import

from copy import deepcopy
import os
import platform
import pytest
import subprocess

from conda_kapsel.test.environ_utils import minimal_environ, strip_environ
from conda_kapsel.test.project_utils import project_no_dedicated_env
from conda_kapsel.internal.test.tmpfile_utils import with_directory_contents
from conda_kapsel.internal import conda_api
from conda_kapsel.prepare import (prepare_without_interaction, prepare_with_browser_ui, unprepare, prepare_in_stages,
                                  PrepareSuccess, PrepareFailure, _after_stage_success, _FunctionPrepareStage)
from conda_kapsel.project import Project
from conda_kapsel.project_file import DEFAULT_PROJECT_FILENAME
from conda_kapsel.project_commands import ProjectCommand
from conda_kapsel.local_state_file import LocalStateFile
from conda_kapsel.plugins.requirement import (EnvVarRequirement, UserConfigOverrides)
from conda_kapsel.conda_manager import (push_conda_manager_class, pop_conda_manager_class, CondaManager,
                                        CondaEnvironmentDeviations)
import conda_kapsel.internal.keyring as keyring


def test_prepare_empty_directory():
    def prepare_empty(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ()
        result = prepare_without_interaction(project, environ=environ)
        assert result
        assert dict(PROJECT_DIR=project.directory_path) == strip_environ(result.environ)
        assert dict() == strip_environ(environ)
        assert result.command_exec_info is None

    with_directory_contents(dict(), prepare_empty)


def test_prepare_bad_provide_mode():
    def prepare_bad_provide_mode(dirname):
        with pytest.raises(ValueError) as excinfo:
            project = project_no_dedicated_env(dirname)
            environ = minimal_environ()
            prepare_in_stages(project, mode="BAD_PROVIDE_MODE", environ=environ)
        assert "invalid provide mode" in repr(excinfo.value)

    with_directory_contents(dict(), prepare_bad_provide_mode)


def test_unprepare_empty_directory():
    def unprepare_empty(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ()
        result = prepare_without_interaction(project, environ=environ)
        assert result
        status = unprepare(project, result)
        assert status

    with_directory_contents(dict(), unprepare_empty)


def test_unprepare_problem_project():
    def unprepare_problems(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ()
        result = prepare_without_interaction(project, environ=environ)
        assert not result
        status = unprepare(project, result)
        assert not status
        assert status.status_description == 'Unable to load the project.'
        assert status.errors == ['variables section contains wrong value type 42, ' +
                                 'should be dict or list of requirements']

    with_directory_contents({DEFAULT_PROJECT_FILENAME: "variables:\n  42"}, unprepare_problems)


def test_unprepare_nothing_to_do():
    def unprepare_nothing(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ()
        result = prepare_without_interaction(project, environ=environ)
        assert result
        status = unprepare(project, result, whitelist=[])
        assert status
        assert status.status_description == 'Nothing to clean up.'

    with_directory_contents(dict(), unprepare_nothing)


def test_default_to_system_environ():
    def prepare_system_environ(dirname):
        project = project_no_dedicated_env(dirname)
        os_environ_copy = deepcopy(os.environ)
        result = prepare_without_interaction(project)
        assert project.directory_path == strip_environ(result.environ)['PROJECT_DIR']
        # os.environ wasn't modified
        assert os_environ_copy == os.environ
        # result.environ inherits everything in os.environ
        for key in os_environ_copy:
            if key == 'PATH' and platform.system() == 'Windows' and result.environ[key] != os.environ[key]:
                print("prepare changed PATH on Windows and ideally it would not.")
            else:
                if key == 'PATH' and result.environ[key] != os.environ[key]:
                    original = os.environ[key].split(os.pathsep)
                    updated = result.environ[key].split(os.pathsep)
                    print("ORIGINAL PATH: " + repr(original))
                    print("UPDATED PATH: " + repr(updated))
                    assert original == updated
                assert result.environ.get(key) == os.environ.get(key)

    with_directory_contents(dict(), prepare_system_environ)


def test_prepare_some_env_var_already_set():
    def prepare_some_env_var(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(FOO='bar')
        result = prepare_without_interaction(project, environ=environ)
        assert result
        assert dict(FOO='bar', PROJECT_DIR=project.directory_path) == strip_environ(result.environ)
        assert dict(FOO='bar') == strip_environ(environ)

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
variables:
  FOO: {}
"""}, prepare_some_env_var)


def test_prepare_some_env_var_not_set():
    def prepare_some_env_var(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(BAR='bar')
        result = prepare_without_interaction(project, environ=environ)
        assert not result
        assert dict(BAR='bar') == strip_environ(environ)

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
variables:
  FOO: {}
"""}, prepare_some_env_var)


def test_prepare_some_env_var_not_set_keep_going():
    def prepare_some_env_var_keep_going(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(BAR='bar')
        stage = prepare_in_stages(project, environ=environ, keep_going_until_success=True)

        # there's an initial stage to set the conda env
        next_stage = stage.execute()
        assert not stage.failed
        assert stage.environ['PROJECT_DIR'] == dirname
        stage = next_stage

        for i in range(1, 10):
            next_stage = stage.execute()
            assert next_stage is not None
            assert stage.failed
            assert stage.environ['PROJECT_DIR'] == dirname
            stage = next_stage
        assert dict(BAR='bar') == strip_environ(environ)

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
variables:
  FOO: {}
"""}, prepare_some_env_var_keep_going)


def test_prepare_with_app_entry():
    def prepare_with_app_entry(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(FOO='bar')
        env_path = conda_api.environ_get_prefix(environ)
        result = prepare_without_interaction(project, environ=environ)
        assert result

        command = result.command_exec_info
        assert 'FOO' in command.env
        assert command.cwd == project.directory_path
        if platform.system() == 'Windows':
            commandpath = os.path.join(env_path, "python.exe")
        else:
            commandpath = os.path.join(env_path, "bin", "python")
        assert command.args == [commandpath, 'echo.py', env_path, 'foo', 'bar']
        p = command.popen(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        # strip is to pull off the platform-specific newline
        assert out.decode().strip() == ("['echo.py', '%s', 'foo', 'bar']" % (env_path.replace("\\", "\\\\")))
        assert err.decode() == ""

    with_directory_contents(
        {DEFAULT_PROJECT_FILENAME: """
variables:
  FOO: {}

commands:
  default:
    conda_app_entry: python echo.py ${PREFIX} foo bar
""",
         "echo.py": """
from __future__ import print_function
import sys
print(repr(sys.argv))
"""}, prepare_with_app_entry)


def test_prepare_choose_command():
    def check(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ()
        result = prepare_without_interaction(project, environ=environ, command_name='foo')
        assert result
        assert result.command_exec_info.bokeh_app == 'foo.py'

        environ = minimal_environ()
        result = prepare_without_interaction(project, environ=environ, command_name='bar')
        assert result
        assert result.command_exec_info.bokeh_app == 'bar.py'

    with_directory_contents(
        {DEFAULT_PROJECT_FILENAME: """
commands:
    foo:
       bokeh_app: foo.py
    bar:
       bokeh_app: bar.py
""",
         "foo.py": "# foo",
         "bar.py": "# bar"}, check)


def test_prepare_command_not_in_project():
    def check(dirname):
        # create a command that isn't in the Project
        project = project_no_dedicated_env(dirname)
        command = ProjectCommand(name="foo",
                                 attributes=dict(bokeh_app="foo.py",
                                                 env_spec=project.default_env_spec_name))
        environ = minimal_environ()
        result = prepare_without_interaction(project, environ=environ, command=command)
        assert result
        assert result.command_exec_info.bokeh_app == 'foo.py'

    with_directory_contents(
        {DEFAULT_PROJECT_FILENAME: """
commands:
  decoy:
    description: "do not use me"
    unix: foobar
    windows: foobar
""",
         "foo.py": "# foo"}, check)


def test_prepare_bad_command_name():
    def check(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(BAR='bar')
        result = prepare_without_interaction(project, environ=environ, command_name="blah")
        assert not result
        assert result.errors
        assert "Command name 'blah' is not in" in result.errors[0]

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
"""}, check)


def _push_fake_env_creator():
    class HappyCondaManager(CondaManager):
        def find_environment_deviations(self, prefix, spec):
            return CondaEnvironmentDeviations(summary="all good",
                                              missing_packages=(),
                                              wrong_version_packages=(),
                                              missing_pip_packages=(),
                                              wrong_version_pip_packages=())

        def fix_environment_deviations(self, prefix, spec, deviations=None):
            pass

        def remove_packages(self, prefix, packages):
            pass

    push_conda_manager_class(HappyCondaManager)


def _pop_fake_env_creator():
    pop_conda_manager_class()


def test_prepare_choose_environment():
    def check(dirname):
        env_var = conda_api.conda_prefix_variable()

        try:
            _push_fake_env_creator()
            project = Project(dirname)
            environ = minimal_environ()
            result = prepare_without_interaction(project, environ=environ, env_spec_name='foo')
            expected_path = project.env_specs['foo'].path(project.directory_path)
            assert result.environ[env_var] == expected_path

            environ = minimal_environ()
            result = prepare_without_interaction(project, environ=environ, env_spec_name='bar')
            assert result
            expected_path = project.env_specs['bar'].path(project.directory_path)
            assert result.environ[env_var] == expected_path
        finally:
            _pop_fake_env_creator()

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
env_specs:
    foo: {}
    bar: {}
"""}, check)


def test_prepare_use_command_specified_env_spec():
    def check(dirname):
        env_var = conda_api.conda_prefix_variable()

        try:
            _push_fake_env_creator()
            project = Project(dirname)
            environ = minimal_environ()
            # we specify the command name but not the
            # env_spec_name but it should imply the proper env
            # spec name.
            result = prepare_without_interaction(project, environ=environ, command_name='hello')
            expected_path = project.env_specs['foo'].path(project.directory_path)
            assert result.environ[env_var] == expected_path
        finally:
            _pop_fake_env_creator()

    with_directory_contents(
        {DEFAULT_PROJECT_FILENAME: """
env_specs:
    default: {}
    foo: {}
    bar: {}
commands:
    hello:
       env_spec: foo
       unix: echo hello
       windows: echo hello
"""}, check)


def test_update_environ():
    def prepare_then_update_environ(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(FOO='bar')
        result = prepare_without_interaction(project, environ=environ)
        assert result

        other = minimal_environ(BAR='baz')
        result.update_environ(other)
        assert dict(FOO='bar', BAR='baz', PROJECT_DIR=dirname) == strip_environ(other)

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
variables:
  FOO: {}
"""}, prepare_then_update_environ)


def test_attempt_to_grab_result_early():
    def early_result_grab(dirname):
        project = project_no_dedicated_env(dirname)
        first_stage = prepare_in_stages(project)
        with pytest.raises(RuntimeError) as excinfo:
            first_stage.result
        assert "result property isn't available" in repr(excinfo.value)

    with_directory_contents(dict(), early_result_grab)


def test_attempt_to_grab_statuses_early():
    def early_status_grab(dirname):
        project = project_no_dedicated_env(dirname)
        first_stage = prepare_in_stages(project)
        with pytest.raises(RuntimeError) as excinfo:
            first_stage.statuses_after_execute
        assert "statuses_after_execute isn't available" in repr(excinfo.value)

    with_directory_contents(dict(), early_status_grab)


def test_skip_after_success_function_when_second_stage_fails():
    state = {'state': 'start'}

    def do_first(stage):
        assert state['state'] == 'start'
        state['state'] = 'first'
        stage.set_result(
            PrepareSuccess(logs=[],
                           statuses=(),
                           command_exec_info=None,
                           environ=dict(),
                           overrides=UserConfigOverrides()),
            [])

        def last(stage):
            assert state['state'] == 'first'
            state['state'] = 'second'
            stage.set_result(
                PrepareFailure(logs=[],
                               statuses=(),
                               errors=[],
                               environ=dict(),
                               overrides=UserConfigOverrides()),
                [])
            return None

        return _FunctionPrepareStage(dict(), UserConfigOverrides(), "second", [], last)

    first_stage = _FunctionPrepareStage(dict(), UserConfigOverrides(), "first", [], do_first)

    def after(updated_statuses):
        raise RuntimeError("should not have been called")

    stage = _after_stage_success(first_stage, after)
    assert stage.overrides is first_stage.overrides
    assert isinstance(stage.environ, dict)
    while stage is not None:
        next_stage = stage.execute()
        result = stage.result
        if result.failed:
            assert stage.failed
            break
        else:
            assert not stage.failed
        stage = next_stage
    assert result.failed
    assert state['state'] == 'second'


def test_run_after_success_function_when_second_stage_succeeds():
    state = {'state': 'start'}

    def do_first(stage):
        assert state['state'] == 'start'
        state['state'] = 'first'
        stage.set_result(
            PrepareSuccess(logs=[],
                           statuses=(),
                           command_exec_info=None,
                           environ=dict(),
                           overrides=UserConfigOverrides()),
            [])

        def last(stage):
            assert state['state'] == 'first'
            state['state'] = 'second'
            stage.set_result(
                PrepareSuccess(logs=[],
                               statuses=(),
                               command_exec_info=None,
                               environ=dict(),
                               overrides=UserConfigOverrides()),
                [])
            return None

        return _FunctionPrepareStage(dict(), UserConfigOverrides(), "second", [], last)

    first_stage = _FunctionPrepareStage(dict(), UserConfigOverrides(), "first", [], do_first)

    def after(updated_statuses):
        assert state['state'] == 'second'
        state['state'] = 'after'

    stage = _after_stage_success(first_stage, after)
    assert stage.overrides is first_stage.overrides
    while stage is not None:
        next_stage = stage.execute()
        result = stage.result
        if result.failed:
            assert stage.failed
            break
        else:
            assert not stage.failed
        stage = next_stage
    assert not result.failed
    assert state['state'] == 'after'


def _form_names(response, provider):
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


def test_prepare_with_browser(monkeypatch):
    from tornado.ioloop import IOLoop
    io_loop = IOLoop()

    http_results = {}

    def mock_open_new_tab(url):
        from conda_kapsel.internal.test.http_utils import http_get_async, http_post_async
        from tornado import gen

        @gen.coroutine
        def do_http():
            http_results['get'] = yield http_get_async(url)

            # pick our environment (using inherited one)
            form_names = _form_names(http_results['get'], provider='CondaEnvProvider')
            form = _prefix_form(form_names, {'source': 'inherited'})
            response = yield http_post_async(url, form=form)
            assert response.code == 200

            # now do the next round of stuff (the FOO variable)
            http_results['post'] = yield http_post_async(url, body="")

        io_loop.add_callback(do_http)

    monkeypatch.setattr('webbrowser.open_new_tab', mock_open_new_tab)

    def prepare_with_browser(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(BAR='bar')
        result = prepare_with_browser_ui(project, environ=environ, keep_going_until_success=False, io_loop=io_loop)
        assert not result
        assert dict(BAR='bar') == strip_environ(environ)

        # wait for the results of the POST to come back,
        # awesome hack-tacular
        while 'post' not in http_results:
            io_loop.call_later(0.01, lambda: io_loop.stop())
            io_loop.start()

        assert 'get' in http_results
        assert 'post' in http_results

        assert 200 == http_results['get'].code
        assert 200 == http_results['post'].code

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
variables:
  FOO: {}
"""}, prepare_with_browser)


def test_prepare_asking_for_password_with_browser(monkeypatch):
    keyring.reset_keyring_module()

    # In this scenario, we store a password in the keyring.
    from tornado.ioloop import IOLoop
    io_loop = IOLoop()

    http_results = {}

    def click_submit(url):
        from conda_kapsel.internal.test.http_utils import http_get_async, http_post_async
        from tornado import gen

        @gen.coroutine
        def do_http():
            http_results['get_click_submit'] = get_response = yield http_get_async(url)

            if get_response.code != 200:
                raise Exception("got a bad http response " + repr(get_response))

            http_results['post_click_submit'] = post_response = yield http_post_async(url, body="")

            assert 200 == post_response.code
            assert '</form>' in str(post_response.body)
            assert 'FOO_PASSWORD' in str(post_response.body)

            fill_in_password(url, post_response)

        io_loop.add_callback(do_http)

    def fill_in_password(url, first_response):
        from conda_kapsel.internal.test.http_utils import http_post_async
        from conda_kapsel.internal.plugin_html import _BEAUTIFUL_SOUP_BACKEND
        from tornado import gen
        from bs4 import BeautifulSoup

        if first_response.code != 200:
            raise Exception("got a bad http response " + repr(first_response))

        # set the FOO_PASSWORD field
        soup = BeautifulSoup(first_response.body, _BEAUTIFUL_SOUP_BACKEND)
        password_fields = soup.find_all("input", attrs={'type': 'password'})
        if len(password_fields) == 0:
            print("No password fields in " + repr(soup))
            raise Exception("password field not found")
        else:
            field = password_fields[0]

        assert 'name' in field.attrs

        @gen.coroutine
        def do_http():
            http_results['post_fill_in_password'] = yield http_post_async(url, form={field['name']: 'bloop'})

        io_loop.add_callback(do_http)

    def mock_open_new_tab(url):
        return click_submit(url)

    monkeypatch.setattr('webbrowser.open_new_tab', mock_open_new_tab)

    def prepare_with_browser(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ()
        result = prepare_with_browser_ui(project, environ=environ, keep_going_until_success=False, io_loop=io_loop)
        assert result
        assert dict(FOO_PASSWORD='bloop', PROJECT_DIR=project.directory_path) == strip_environ(result.environ)
        assert dict() == strip_environ(environ)

        # wait for the results of the POST to come back,
        # awesome hack-tacular
        while 'post_fill_in_password' not in http_results:
            io_loop.call_later(0.01, lambda: io_loop.stop())
            io_loop.start()

        assert 'get_click_submit' in http_results
        assert 'post_click_submit' in http_results
        assert 'post_fill_in_password' in http_results

        assert 200 == http_results['get_click_submit'].code
        assert 200 == http_results['post_click_submit'].code
        assert 200 == http_results['post_fill_in_password'].code

        final_done_html = str(http_results['post_fill_in_password'].body)
        assert "Done!" in final_done_html
        assert "Environment variable FOO_PASSWORD is set." in final_done_html

        local_state_file = LocalStateFile.load_for_directory(project.directory_path)
        assert local_state_file.get_value(['variables', 'FOO_PASSWORD']) is None

        # now a no-browser prepare() should read password from the
        # keyring

    keyring.enable_fallback_keyring()
    try:
        with_directory_contents({DEFAULT_PROJECT_FILENAME: """
variables:
  FOO_PASSWORD: {}
"""}, prepare_with_browser)
    finally:
        keyring.disable_fallback_keyring()


def test_prepare_problem_project_with_browser(monkeypatch):
    def check(dirname):
        project = project_no_dedicated_env(dirname)
        environ = minimal_environ(BAR='bar')
        result = prepare_with_browser_ui(project, environ=environ, keep_going_until_success=False)
        assert not result
        assert dict(BAR='bar') == strip_environ(environ)

        assert [('Icon file %s does not exist.' % os.path.join(dirname, 'foo.png')), 'Unable to load the project.'
                ] == result.errors

    with_directory_contents({DEFAULT_PROJECT_FILENAME: """
icon: foo.png
"""}, check)


def test_prepare_success_properties():
    result = PrepareSuccess(logs=["a"],
                            statuses=(),
                            command_exec_info=None,
                            environ=dict(),
                            overrides=UserConfigOverrides())
    assert result.statuses == ()
    assert result.status_for('FOO') is None
    assert result.status_for(EnvVarRequirement) is None
    assert result.overrides is not None
