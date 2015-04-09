# -*- coding: utf-8 -*-
#                     The LLVM Compiler Infrastructure
#
# This file is distributed under the University of Illinois Open Source
# License. See LICENSE.TXT for details.

""" This module is responsible for to transform the arguments of a compilation
into an analyzer invocation. To execute the analyzer is done in other module.
"""


import logging
import re
import os
import os.path
import shlex
import json
import functools
from analyzer.decorators import trace, require


@trace
def generate_commands(args):
    """ From compilation database it creates analyzer commands. """

    def extend(opts, direct_args):
        """ Take a compilation database entry and extend it with classified
        compiler parameters and direct arguments from command line.
        """
        opts.update(classify_parameters(shlex.split(opts['command'])))
        opts.update({'direct_args': direct_args})
        return opts

    direct_args = _analyzer_params(args)
    with open(args.cdb, 'r') as handle:
        generator = (extend(cmd, direct_args) for cmd in json.load(handle))

    return (cmd
            for cmd
            in (_action_check(cmd) for cmd in generator)
            if cmd is not None)


class Action(object):
    """ Enumeration class for compiler action. """
    Link, Compile, Preprocess, Info = range(4)


@trace
def classify_parameters(command):
    """ Parses the command line arguments of the given invocation.

    To run analysis from a compilation command, first it disassembles the
    compilation command. Classifies the parameters into groups and throws
    away those which are not relevant.
    """
    def match(state, iterator):
        """ This method contains a list of pattern and action tuples.
            The matching start from the top if the list, when the first
            match happens the action is executed.
        """
        def regex(pattern, action):
            regexp = re.compile(pattern)

            def evaluate(iterator):
                match = regexp.match(iterator.current())
                if match:
                    action(state, iterator, match)
                    return True
            return evaluate

        def anyof(opts, action):
            def evaluate(iterator):
                if iterator.current() in opts:
                    action(state, iterator, None)
                    return True
            return evaluate

        tasks = [
            #
            regex(r'^-(E|MM?)$', take_action(Action.Preprocess)),
            anyof({'-c'}, take_action(Action.Compile)),
            anyof({'-print-prog-name'}, take_action(Action.Info)),
            anyof({'-cc1'}, take_action(Action.Info)),
            #
            anyof({'-arch'}, take_two('archs_seen')),
            #
            anyof({'-filelist'}, take_from_file('files')),
            regex(r'^[^-].+', take_one('files')),
            #
            anyof({'-x'}, take_second('language')),
            #
            anyof({'-o'}, take_second('output')),
            #
            anyof({'-write-strings',
                   '-v'}, take_one('compile_options')),
            anyof({'-ftrapv-handler',
                   '--sysroot',
                   '-target'}, take_two('compile_options')),
            regex(r'^-isysroot', take_two('compile_options')),
            regex(r'^-m(32|64)$', take_one('compile_options')),
            regex(r'^-mios-simulator-version-min(.*)',
                  take_joined('compile_options')),
            regex(r'^-stdlib(.*)', take_joined('compile_options')),
            regex(r'^-mmacosx-version-min(.*)',
                  take_joined('compile_options')),
            regex(r'^-miphoneos-version-min(.*)',
                  take_joined('compile_options')),
            regex(r'^-O[1-3]$', take_one('compile_options')),
            anyof({'-O'}, take_as('-O1', 'compile_options')),
            anyof({'-Os'}, take_as('-O2', 'compile_options')),
            regex(r'^-[DIU](.*)$', take_joined('compile_options')),
            anyof({'-nostdinc'}, take_one('compile_options')),
            regex(r'^-std=', take_one('compile_options')),
            regex(r'^-include', take_two('compile_options')),
            anyof({'-idirafter',
                   '-imacros',
                   '-iprefix',
                   '-isystem',
                   '-iwithprefix',
                   '-iwithprefixbefore'}, take_two('compile_options')),
            regex(r'^-m.*', take_one('compile_options')),
            regex(r'^-iquote(.*)', take_joined('compile_options')),
            regex(r'^-Wno-', take_one('compile_options')),
            # ignore
            regex(r'^-framework$', take_two()),
            regex(r'^-fobjc-link-runtime(.*)', take_joined()),
            regex(r'^-[lL]', take_one()),
            regex(r'^-M[TF]$', take_two()),
            regex(r'^-[eu]$', take_two()),
            anyof({'-fsyntax-only',
                   '-save-temps'}, take_one()),
            anyof({'-install_name',
                   '-exported_symbols_list',
                   '-current_version',
                   '-compatibility_version',
                   '-init',
                   '-seg1addr',
                   '-bundle_loader',
                   '-multiply_defined',
                   '--param',
                   '--serialize-diagnostics'}, take_two()),
            anyof({'-sectorder'}, take_four()),
            #
            regex(r'^-[fF](.+)$', take_one('compile_options'))
        ]
        for task in tasks:
            if task(iterator):
                return

    def take_n(count=1, *keys):
        def take(values, iterator, _match):
            updates = []
            updates.append(iterator.current())
            for _ in range(count - 1):
                updates.append(iterator.next())
            for key in keys:
                current = values.get(key, [])
                values.update({key: current + updates})
        return take

    def take_one(*keys):
        return take_n(1, *keys)

    def take_two(*keys):
        return take_n(2, *keys)

    def take_four(*keys):
        return take_n(4, *keys)

    def take_joined(*keys):
        def take(values, iterator, match):
            updates = []
            updates.append(iterator.current())
            if not match.group(1):
                updates.append(iterator.next())
            for key in keys:
                current = values.get(key, [])
                values.update({key: current + updates})
        return take

    def take_from_file(*keys):
        def take(values, iterator, _match):
            with open(iterator.next()) as handle:
                current = [line.strip() for line in handle.readlines()]
                for key in keys:
                    values[key] = current
        return take

    def take_as(value, *keys):
        def take(values, _iterator, _match):
            updates = [value]
            for key in keys:
                current = values.get(key, [])
                values.update({key: current + updates})
        return take

    def take_second(*keys):
        def take(values, iterator, _match):
            current = iterator.next()
            for key in keys:
                values[key] = current
        return take

    def take_action(action):
        def take(values, _iterator, _match):
            key = 'action'
            current = values[key]
            values[key] = max(current, action)
        return take

    state = {'action': Action.Link,
             'cxx': _is_cplusplus_compiler(command[0])}

    arguments = Arguments(command)
    for _ in arguments:
        match(state, arguments)
    return state


class Arguments(object):
    """ An iterator wraper around compiler arguments.

    Python iterators are only implement the 'next' method, but this one
    implements the 'current' query method as well.
    """
    def __init__(self, args):
        """ Takes the full command line, but iterates on the parameters only.
        """
        self.__sequence = args[1:]
        self.__size = len(self.__sequence)
        self.__current = -1

    def __iter__(self):
        """ Needed for python iterator.
        """
        return self

    def __next__(self):
        """ Needed for python iterator. (version 3.x)
        """
        return self.next()

    def next(self):
        """ Needed for python iterator. (version 2.x)
        """
        self.__current += 1
        return self.current()

    def current(self):
        """ Extra method to query the current element.
        """
        if self.__current >= self.__size:
            raise StopIteration
        else:
            return self.__sequence[self.__current]


def _is_cplusplus_compiler(name):
    """ Returns true when the compiler name refer to a C++ compiler.
    """
    match = re.match(r'^([^/]*/)*(\w*-)*(\w+\+\+)(-(\d+(\.\d+){0,3}))?$', name)
    return False if match is None else True


@trace
def _analyzer_params(args):
    """ A group of command line arguments can mapped to command
    line arguments of the analyzer. This method generates those. """
    result = []

    extend_result = lambda pieces, prefix: \
        functools.reduce(lambda acc, x: acc + [prefix, x], pieces, result)

    if args.store_model:
        result.append('-analyzer-store={0}'.format(args.store_model))
    if args.constraints_model:
        result.append(
            '-analyzer-constraints={0}'.format(args.constraints_model))
    if args.internal_stats:
        result.append('-analyzer-stats')
    if args.analyze_headers:
        result.append('-analyzer-opt-analyze-headers')
    if args.stats:
        result.append('-analyzer-checker=debug.Stats')
    if args.maxloop:
        result.extend(['-analyzer-max-loop', str(args.maxloop)])
    if args.output_format:
        result.append('-analyzer-output={0}'.format(args.output_format))
    if args.analyzer_config:
        result.append(args.analyzer_config)
    if 2 <= args.verbose:
        result.append('-analyzer-display-progress')
    if args.plugins:
        extend_result(args.plugins, '-load')
    if args.enable_checker:
        extend_result(args.enable_checker, '-analyzer-checker')
    if args.disable_checker:
        extend_result(args.disable_checker, '-analyzer-disable-checker')
    if args.ubiviz:
        result.append('-analyzer-viz-egraph-ubigraph')
    return functools.reduce(lambda acc, x: acc + ['-Xclang', x], result, [])


@trace
@require(['directory', 'file', 'language', 'direct_args'])
def _create_commands(opts):
    """ Create command to run analyzer or failure report generation.

    If output is passed it returns failure report command.
    If it's not given it returns the analyzer command. """
    common = []
    if 'arch' in opts:
        common.extend(['-arch', opts['arch']])
    if 'compile_options' in opts:
        common.extend(opts['compile_options'])
    common.extend(['-x', opts['language']])
    common.append(opts['file'])

    return {
        'directory': opts['directory'],
        'file': opts['file'],
        'language': opts['language'],
        'analyze': ['--analyze'] + opts['direct_args'] + common,
        'report': ['-fsyntax-only', '-E'] + common}


@trace
@require(['file'])
def _language_check(opts, continuation=_create_commands):
    """ Find out the language from command line parameters or file name
    extension. The decision also influenced by the compiler invocation. """
    def from_filename(name, cplusplus_compiler):
        mapping = {
            '.c': 'c++' if cplusplus_compiler else 'c',
            '.cp': 'c++',
            '.cpp': 'c++',
            '.cxx': 'c++',
            '.txx': 'c++',
            '.cc': 'c++',
            '.C': 'c++',
            '.ii': 'c++-cpp-output',
            '.i': 'c++-cpp-output' if cplusplus_compiler else 'c-cpp-output',
            '.m': 'objective-c',
            '.mi': 'objective-c-cpp-output',
            '.mm': 'objective-c++',
            '.mii': 'objective-c++-cpp-output'
        }
        (_, extension) = os.path.splitext(os.path.basename(name))
        return mapping.get(extension)

    accepteds = {
        'c',
        'c++',
        'objective-c',
        'objective-c++',
        'c-cpp-output',
        'c++-cpp-output',
        'objective-c-cpp-output'
    }

    key = 'language'
    language = opts[key] if key in opts else \
        from_filename(opts['file'], opts.get('cxx', False))
    if language is None:
        logging.debug('skip analysis, language not known')
    elif language not in accepteds:
        logging.debug('skip analysis, language not supported')
    else:
        logging.debug('analysis, language: {0}'.format(language))
        opts.update({key: language})
        return continuation(opts)
    return None


@trace
@require([])
def _arch_check(opts, continuation=_language_check):
    """ Do run analyzer through one of the given architectures. """
    disableds = {'ppc', 'ppc64'}

    key = 'archs_seen'
    if key in opts:
        archs = [a for a in opts[key] if '-arch' != a and a not in disableds]
        if not archs:
            logging.debug('skip analysis, found not supported arch')
            return None
        else:
            # There should be only one arch given (or the same multiple times)
            # If there are multiple arch are given, and those are not the same
            # those should not change the pre-processing step. (But that's the
            # only pass we have before run the analyzer.)
            arch = archs.pop()
            logging.debug('analysis, on arch: {0}'.format(arch))

            opts.update({'arch': arch})
            del opts[key]
            return continuation(opts)
    else:
        logging.debug('analysis, on default arch')
        return continuation(opts)


@trace
@require(['action'])
def _action_check(opts, continuation=_arch_check):
    """ Continue analysis only if it compilation or link. """
    return continuation(opts) if opts['action'] <= Action.Compile else None
