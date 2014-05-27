# -*- coding: utf-8 -*-

# Copyright 2013 by László Nagy
# This file is part of Beye [see file LICENSE.txt for more]

import subprocess
import logging
import re
import os
import os.path
import sys
import tempfile
import copy
import functools
import shlex


def main():
    def split_env_content(name):
        content = os.environ.get(name)
        return content.split() if content else None

    if (os.environ.get('CCC_ANALYZER_VERBOSE')):
        log_level = loggin.DEBUG
    elif (os.environ.get('CCC_ANALYZER_LOG')):
        log_level = loggin.INFO
    else:
        log_level = logging.WARNING

    logging.basicConfig(format='%(message)s', level=log_level)
    logging.info(' '.join(sys.argv))

    return run(
        command=sys.argv,
        is_cxx=('c++-analyzer' == sys.argv[0]),
        verbose=True if log_level < loggin.WARNING else None,
        analyses=split_env_content('CCC_ANALYZER_ANALYSIS'),
        plugins=split_env_content('CCC_ANALYZER_PLUGINS'),
        config=split_env_content('CCC_ANALYZER_CONFIG'),
        store_model=os.environ.get('CCC_ANALYZER_STORE_MODEL'),
        constraints_model=os.environ.get('CCC_ANALYZER_CONSTRAINTS_MODEL'),
        internal_stats=os.environ.get('CCC_ANALYZER_INTERNAL_STATS'),
        output_format=os.environ.get('CCC_ANALYZER_OUTPUT_FORMAT', 'html'),
        html_dir=os.environ.get('CCC_ANALYZER_HTML'),
        ubiviz=os.environ.get('CCC_UBI'),
        report_failures=os.environ.get('CCC_REPORT_FAILURES'))


""" Main method to run the analysis.

    The analysis is written continuation-passing style. Each step takes
    two arguments: the current analysis state, and the continuation to
    call on success.
"""


def run(**kwargs):
    def stack(conts):
        def bind(cs, acc):
            return bind(cs[1:], lambda x: cs[0](x, acc)) if cs else acc

        conts.reverse()
        return bind(conts, lambda x: x)

    chain = stack([set_compiler,
                   execute,
                   parse,
                   filter_action,
                   arch_loop,
                   files_loop,
                   set_language,
                   set_directory,
                   set_analyzer_output,
                   run_analyzer,
                   report_failure])

    return chain(kwargs)


""" Decorator to simplify debugging.
"""


def trace(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        logging.debug('entering {0}'.format(fn.__name__))
        result = fn(*args, **kwargs)
        logging.debug('leaving {0}'.format(fn.__name__))
        return result

    return wrapper


""" Decorator to simplify debugging.
"""


def continuation(expecteds=[]):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(opts, cont):
            logging.debug('opts {0}'.format(opts))
            try:
                for expected in expecteds:
                    if expected not in opts:
                        raise KeyError(
                            '{0} not passed to {1}'.format(
                                expected,
                                fn.__name__))

                return fn(opts, cont)
            except Exception as e:
                logging.error(str(e))
                return None

        return wrapper

    return decorator


""" Utility function to isolate changes on dictionaries.

    It only creates shallow copy of the input dictionary. So, modifying
    values are not isolated. But to remove and add new ones are safe.
"""


def filter_dict(original, removables, additions):
    new = dict()
    for (k, v) in original.items():
        if v and k not in removables:
            new[k] = v
    for (k, v) in additions.items():
        new[k] = v
    return new


""" Detect compilers from environment/architecture.
"""


@trace
@continuation(['is_cxx'])
def set_compiler(opts, continuation):
    match = re.match('Darwin', subprocess.check_output(['uname', '-a']))
    cc_compiler = 'clang' if match else 'gcc'
    cxx_compiler = 'clang++' if match else 'g++'

    if opts['is_cxx']:
        compiler = os.environ.get('CCC_CXX', cxx_compiler)
        clang = os.environ.get('CLANG_CXX', 'clang++')
    else:
        compiler = os.environ.get('CCC_CC', cc_compiler)
        clang = os.environ.get('CLANG_CXX', 'clang')

    return continuation(
        filter_dict(opts, frozenset(), {'clang': clang, 'compiler': compiler}))


""" This method execute the original compiler call as it was given,
    to create those artifacts which is required by the build sysyem.
    And the exit code also comming from this step.
"""


@trace
@continuation(['command', 'compiler'])
def execute(opts, continuation):
    result = subprocess.call(compiler + opts['command'][1:])
    continuation(filter_dict(opts, frozenset(['compiler']), dict()))
    return result


""" Enumeration class for compiler action.
"""


class Action:
    Link, Compile, Preprocess, Info = range(4)


""" This method parses the command line arguments of the current invocation.
"""


@trace
@continuation(['command'])
def parse(opts, continuation):
    """ This method contains a list of pattern and action tuples.
        The matching start from the top if the list, when the first
        match happens the action is executed.
    """
    def match(state, it):
        def regex(pattern, action):
            regexp = re.compile(pattern)

            def eval(it):
                match = regexp.match(it.current)
                if match:
                    action(state, it, match)
                    return True
            return eval

        def anyof(opts, action):
            def eval(it):
                if it.current in frozenset(opts):
                    action(state, it, None)
                    return True
            return eval

        tasks = [
            #
            regex('^-(E|MM?)$', take_action(Action.Preprocess)),
            anyof(['-c'], take_action(Action.Compile)),
            anyof(['-print-prog-name'], take_action(Action.Info)),
            #
            anyof(['-arch'], take_two('archs_seen', 'compile_options',
                                      'link_options')),
            #
            anyof(['-filelist'], take_from_file('files')),
            regex('^[^-].+', take_one('files')),
            #
            anyof(['-x'], take_second('language')),
            #
            anyof(['-o'], take_second('output')),
            #
            anyof(['-write-strings',
                   '-v'], take_one('compile_options', 'link_options')),
            anyof(['-ftrapv-handler',
                   '--sysroot',
                   '-target'], take_two('compile_options', 'link_options')),
            regex('^-isysroot', take_two('compile_options', 'link_options')),
            regex('^-m(32|64)$', take_one('compile_options', 'link_options')),
            regex('^-mios-simulator-version-min(.*)',
                  take_joined('compile_options', 'link_options')),
            regex('^-stdlib(.*)',
                  take_joined('compile_options', 'link_options')),
            regex('^-mmacosx-version-min(.*)',
                  take_joined('compile_options', 'link_options')),
            regex('^-miphoneos-version-min(.*)',
                  take_joined('compile_options', 'link_options')),
            regex('^-O[1-3]$', take_one('compile_options', 'link_options')),
            anyof(['-O'], take_as('-O1', 'compile_options', 'link_options')),
            anyof(['-Os'], take_as('-O2', 'compile_options', 'link_options')),
            #
            regex('^-[DIU](.*)$', take_joined('compile_options')),
            anyof(['-nostdinc'], take_one('compile_options')),
            regex('^-std=', take_one('compile_options')),
            regex('^-include', take_two('compile_options')),
            anyof(['-idirafter',
                   '-imacros',
                   '-iprefix',
                   '-isystem',
                   '-iwithprefix',
                   '-iwithprefixbefore'], take_two('compile_options')),
            regex('^-m.*', take_one('compile_options')),
            regex('^-iquote(.*)', take_joined('compile_options')),
            regex('^-Wno-', take_one('compile_options')),
            #
            regex('^-framework$', take_two('link_options')),
            regex('^-fobjc-link-runtime(.*)', take_joined('link_options')),
            regex('^-[lL]', take_one('link_options')),
            # ignore
            regex('^-M[TF]$', take_two()),
            regex('^-[eu]$', take_two()),
            anyof(['-fsyntax-only',
                   '-save-temps'], take_one()),
            anyof(['-install_name',
                   '-exported_symbols_list',
                   '-current_version',
                   '-compatibility_version',
                   '-init',
                   '-seg1addr',
                   '-bundle_loader',
                   '-multiply_defined',
                   '-sectorder',
                   '--param',
                   '--serialize-diagnostics'], take_two()),
            #
            regex('^-[fF](.+)$', take_one('compile_options', 'link_options'))
        ]
        for task in tasks:
            if task(it):
                return

    def extend(values, key, value):
        if key in values:
            values.get(key).extend(value)
        else:
            values[key] = copy.copy(value)

    def take_n(n=1, *keys):
        def take(values, it, _m):
            current = []
            current.append(it.current)
            for _ in range(n - 1):
                current.append(it.next())
            for key in keys:
                extend(values, key, current)
        return take

    def take_one(*keys):
        return take_n(1, *keys)

    def take_two(*keys):
        return take_n(2, *keys)

    def take_four(*keys):
        return take_n(4, *keys)

    def take_joined(*keys):
        def take(values, it, match):
            current = []
            current.append(it.current)
            if not match.group(1):
                current.append(it.next())
            for key in keys:
                extend(values, key, current)
        return take

    def take_from_file(*keys):
        def take(values, it, _m):
            with open(it.next()) as f:
                current = [l.strip() for l in f.readlines()]
                for key in keys:
                    values[key] = current
        return take

    def take_as(value, *keys):
        def take(values, it, _m):
            current = [value]
            for key in keys:
                extend(values, key, current)
        return take

    def take_second(*keys):
        def take(values, it, _m):
            current = it.next()
            for key in keys:
                values[key] = current
        return take

    def take_action(action):
        def take(values, _it, _m):
            key = 'action'
            current = values[key]
            values[key] = max(current, action)
        return take

    class ArgumentIterator:

        def __init__(self, args):
            self.current = None
            self.__it = iter(args)

        def next(self):
            self.current = next(self.__it) if 3 == sys.version_info[0] \
                else self.__it.next()
            return self.current

    state = {'action': Action.Link}
    try:
        cmd = shlex.split(opts['command'])
        it = ArgumentIterator(cmd[1:])
        while True:
            it.next()
            match(state, it)
    except StopIteration:
        return continuation(filter_dict(opts, frozenset(['command']), state))
    except:
        logging.exception('parsing failed')


""" Continue analysis only if it compilation or link.
"""


@trace
@continuation(['action'])
def filter_action(opts, continuation):
    return continuation(opts) if opts['action'] <= Action.Compile else 0


@trace
@continuation()
def arch_loop(opts, continuation):
    disableds = ['ppc', 'ppc64']

    key = 'archs_seen'
    if key in opts:
        archs = [a for a in opts[key] if '-arch' != a and a not in disableds]
        if archs:
            for arch in archs:
                logging.info('analysis, on arch: {0}'.format(arch))
                status = continuation(
                    filter_dict(opts, frozenset([key]), {'arch': arch}))
                if status != 0:
                    return status
        else:
            logging.info('skip analysis, found not supported arch')
            return 0
    else:
        logging.info('analysis, on default arch')
        return continuation(opts)


@trace
@continuation()
def files_loop(opts, continuation):
    if 'files' in opts:
        for fn in opts['files']:
            logging.info('analysis, source file: {0}'.format(fn))
            status = continuation(
                filter_dict(opts, frozenset(['files']), {'file': fn}))
            if status != 0:
                return status
    else:
        logging.info('skip analysis, source file not found')
        return 0


@trace
@continuation(['file'])
def set_language(opts, continuation):
    def from_filename(fn, is_cxx):
        mapping = {
            '.c': 'c++' if is_cxx else 'c',
            '.cp': 'c++',
            '.cpp': 'c++',
            '.cxx': 'c++',
            '.txx': 'c++',
            '.cc': 'c++',
            '.C': 'c++',
            '.ii': 'c++-cpp-output',
            '.i': 'c++-cpp-output' if is_cxx else 'c-cpp-output',
            '.m': 'objective-c',
            '.mi': 'objective-c-cpp-output',
            '.mm': 'objective-c++',
            '.mii': 'objective-c++-cpp-output'
        }
        (_, extension) = os.path.splitext(os.path.basename(fn))
        return mapping.get(extension)

    accepteds = [
        'c',
        'c++',
        'objective-c',
        'objective-c++',
        'c-cpp-output',
        'c++-cpp-output',
        'objective-c-cpp-output'
    ]

    key = 'language'
    language = opts[key] if key in opts else \
        from_filename(opts['file'], opts.get('is_cxx'))
    if language is None:
        logging.info('skip analysis, language not known')
    elif language not in accepteds:
        logging.info('skip analysis, language not supported')
    else:
        logging.info('analysis, language: {0}'.format(language))
        return continuation(
            filter_dict(opts, frozenset([key]), {key: language}))
    return 0


@trace
@continuation()
def set_directory(opts, continuation):
    if 'directory' not in opts:
        opts['directory'] = os.getcwd()
    return continuation(opts)


@trace
@continuation(['html_dir'])
def set_analyzer_output(opts, continuation):
    @trace
    def create_analyzer_output():
        (fd, name) = tempfile.mkstemp(suffix='.plist',
                                      prefix='report-',
                                      dir=opts['html_dir'])
        os.close(fd)
        logging.info('analyzer output: {0}'.format(name))
        return name

    @trace
    def cleanup_when_needed(fn):
        try:
            if 0 == os.stat(fn).st_size:
                os.remove(fn)
        except:
            logging.warning('cleanup on analyzer output failed {0}'.format(fn))

    if 'plist' == opts.get('output_format'):
        fn = create_analyzer_output()
        status = continuation(
            filter_dict(opts, frozenset(), {'analyzer_output': fn}))
        cleanup_when_needed(fn)
        return status
    return continuation(opts)


@trace
@continuation(['language', 'directory', 'file', 'clang'])
def run_analyzer(opts, continuation):
    cwd = opts['directory']
    cmd = get_clang_arguments(cwd, build_args(opts))
    logging.debug('exec command in {0}: {1}'.format(cwd, ' '.join(cmd)))
    child = subprocess.Popen(cmd,
                             cwd=cwd,
                             universal_newlines=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    child.wait()
    output = child.stdout.readlines()
    # copy to stderr
    for line in output:
        sys.stderr.write(line)
    # do report details if it were asked
    if 'report_failures' in opts:
        error_type = None
        attributes_not_handled = set()

        if (child.returncode & 127):
            error_type = 'crash'
        elif child.returncode:
            error_type = 'other_error'
        else:
            regexp = re.compile("warning: '([^\']+)' attribute ignored")
            for line in output:
                match = regexp.match(it.current)
                if match:
                    error_type = 'attribute_ignored'
                    attributes_not_handled.add(match.group(1))

        if error_type:
            return continuation(
                filter_dict(opts,
                            frozenset(),
                            {'error_type': error_type,
                             'error_output': output,
                             'not_handled_attributes': attributes_not_handled,
                             'exit_code': child.returncode}))

    return child.returncode


@trace
@continuation(['language',
               'directory',
               'file',
               'clang',
               'html_dir',
               'error_type',
               'error_output',
               'exit_code'])
def report_failure(opts, continuation):
    def preprocessor_ext(language):
        mapping = {
            'objective-c++': '.mii',
            'objective-c': '.mi',
            'c++': '.ii'
        }
        return mapping.get(language, '.i')

    def failure_dir(opts):
        name = os.path.abspath(opts['html_dir'] + '/failures')
        if not os.path.isdir(name):
            os.makedirs(name)
        return name

    error = opts['error_type']
    (fd, name) = tempfile.mkstemp(suffix=preprocessor_ext(opts['language']),
                                  prefix='clang_' + error,
                                  dir=failure_dir(opts))
    os.close(fd)
    cwd = opts['directory']
    cmd = get_clang_arguments(cwd, build_args(opts, True)) + ['-E', '-o', name]
    logging.debug('exec command in {0}: {1}'.format(cwd, ' '.join(cmd)))
    child = subprocess.Popen(cmd, cwd=cwd)
    child.wait()

    with open(name + '.info.txt', 'w') as ifd:
        ifd.write(os.path.abspath(opts['file']) + os.linesep)
        ifd.write(error.title().replace('_', ' ') + os.linesep)
        ifd.write(' '.join(cmd) + os.linesep)
        ifd.write(subprocess.check_output(['uname', '-a']))
        ifd.write(
            subprocess.check_output([cmd[0], '-v'], stderr=subprocess.STDOUT))
        ifd.close()

    with open(name + '.stderr.txt', 'w') as efd:
        for line in opts['error_output']:
            efd.write(line)
        efd.close()

    for attr in opts['not_handled_attributes']:
        with open(failure_dir(opts) + 'attribute_ignored_' + attr + '.txt',
                  'a') as fd:
            fd.write(os.path.basename(name))
            fd.close()

    return opts['exit_code']


@trace
def get_clang_arguments(cwd, cmd):
    def lastline(stream):
        last = None
        for line in stream:
            last = line
        if last is None:
            raise Exception("output not found")
        return last

    def strip_quotes(quoted):
        match = re.match('^\"([^\"]*)\"$', quoted)
        return match.group(1) if match else quoted

    try:
        logging.debug('exec command in {0}: {1}'.format(cwd, ' '.join(cmd)))
        child = subprocess.Popen(cmd,
                                 cwd=cwd,
                                 universal_newlines=True,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
        child.wait()
        if 0 == child.returncode:
            return [
                strip_quotes(x) for x in shlex.split(lastline(child.stdout))]
        else:
            raise Exception(lastline(child.stdout))
    except Exception as e:
        logging.error('exec failed: {0}'.format(str(e)))
        return None


def build_args(opts, syntax_only=False):
    def syntax_check():
        result = []
        if 'arch' in opts:
            result.extend(['-arch', opts['arch']])
        if 'compile_options' in opts:
            result.extend(opts['compile_options'])
        result.extend(['-x', opts['language']])
        result.append(opts['file'])
        return result

    def output():
        result = []
        if 'analyzer_output' in opts:
            result.extend(['-o', opts['analyzer_output']])
        elif 'html_dir' in opts:
            result.extend(['-o', opts['html_dir']])
        return result

    def static_analyzer():
        result = []
        if 'store_model' in opts:
            result.append('-analyzer-store={0}'.format(opts['store_model']))
        if 'constraints_model' in opts:
            result.append(
                '-analyzer-constraints={0}'.format(opts['constraints_model']))
        if 'internal_stats' in opts:
            result.append('-analyzer-stats')
        if 'analyses' in opts:
            result.extend(opts['analyses'])
        if 'plugins' in opts:
            result.extend(opts['plugins'])
        if 'output_format' in opts:
            result.append('-analyzer-output={0}'.format(opts['output_format']))
        if 'config' in opts:
            result.append(opts['config'])
        if 'verbose' in opts:
            result.append('-analyzer-display-progress')
        if 'ubiviz' in opts:
            result.append('-analyzer-viz-egraph-ubigraph')
        return functools.reduce(
            lambda acc, x: acc + ['-Xclang', x], result, [])

    if syntax_only:
        return [opts['clang'], '-###', '-fsyntax-only'] + syntax_check()
    else:
        return [opts['clang'], '-###', '--analyze'] + syntax_check() + \
            output() + static_analyzer()