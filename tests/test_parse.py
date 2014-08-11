# -*- coding: utf-8 -*-
#                     The LLVM Compiler Infrastructure
#
# This file is distributed under the University of Illinois Open Source
# License. See LICENSE.TXT for details.

import analyzer.driver as sut
import unittest


class ParseTest(unittest.TestCase):

    def test_action(self):
        def test(expected, cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            self.assertEqual(expected, opts['action'])

        Info = sut.Action.Info
        test(Info, ['clang', 'source.c', '-print-prog-name'])

        Link = sut.Action.Link
        test(Link, ['clang', 'source.c'])

        Compile = sut.Action.Compile
        test(Compile, ['clang', '-c', 'source.c'])
        test(Compile, ['clang', '-c', 'source.c', '-MF', 'source.d'])

        Preprocess = sut.Action.Preprocess
        test(Preprocess, ['clang', '-E', 'source.c'])
        test(Preprocess, ['clang', '-c', '-E', 'source.c'])
        test(Preprocess, ['clang', '-c', '-M', 'source.c'])
        test(Preprocess, ['clang', '-c', '-MM', 'source.c'])

    def test_optimalizations(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            return opts.get('compile_options', [])

        self.assertEqual(['-O1'], test(['clang', '-c', 'source.c', '-O']))
        self.assertEqual(['-O1'], test(['clang', '-c', 'source.c', '-O1']))
        self.assertEqual(['-O2'], test(['clang', '-c', 'source.c', '-Os']))
        self.assertEqual(['-O2'], test(['clang', '-c', 'source.c', '-O2']))
        self.assertEqual(['-O3'], test(['clang', '-c', 'source.c', '-O3']))

    def test_language(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            return opts.get('language')

        self.assertEqual(None, test(['clang', '-c', 'source.c']))
        self.assertEqual('c', test(['clang', '-c', 'source.c', '-x', 'c']))
        self.assertEqual('cpp', test(['clang', '-c', 'source.c', '-x', 'cpp']))

    def test_arch(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            return opts.get('archs_seen', [])

        eq = self.assertEqual

        eq([], test(['clang', '-c', 'source.c']))
        eq(['-arch', 'mips'],
           test(['clang', '-c', 'source.c', '-arch', 'mips']))
        eq(['-arch', 'mips', '-arch', 'i386'],
           test(['clang', '-c', 'source.c', '-arch', 'mips', '-arch', 'i386']))

    def test_input_file(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            return opts.get('files', [])

        eq = self.assertEqual

        eq(['src.c'], test(['clang', 'src.c']))
        eq(['src.c'], test(['clang', '-c', 'src.c']))
        eq(['s1.c', 's2.c'], test(['clang', '-c', 's1.c', 's2.c']))

    def test_output_file(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            return opts.get('output', None)

        eq = self.assertEqual

        eq(None, test(['clang', 'src.c']))
        eq('src.o', test(['clang', '-c', 'src.c', '-o', 'src.o']))
        eq('src.o', test(['clang', '-c', '-o', 'src.o', 'src.c']))

    def test_include(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            self.assertEqual(None, opts.get('link_options'))
            return opts.get('compile_options', [])

        eq = self.assertEqual

        eq([], test(['clang', '-c', 'src.c']))
        eq(['-include', '/usr/local/include'],
           test(['clang', '-c', 'src.c', '-include', '/usr/local/include']))
        eq(['-I.'],
           test(['clang', '-c', 'src.c', '-I.']))
        eq(['-I', '.'],
           test(['clang', '-c', 'src.c', '-I', '.']))
        eq(['-I/usr/local/include'],
           test(['clang', '-c', 'src.c', '-I/usr/local/include']))
        eq(['-I', '/usr/local/include'],
           test(['clang', '-c', 'src.c', '-I', '/usr/local/include']))
        eq(['-I/opt', '-I', '/opt/otp/include'],
           test(['clang', '-c', 'src.c', '-I/opt', '-I', '/opt/otp/include']))

    def test_define(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            self.assertEqual(None, opts.get('link_options'))
            return opts.get('compile_options', [])

        eq = self.assertEqual

        eq([], test(['clang', '-c', 'src.c']))
        eq(['-DNDEBUG'],
           test(['clang', '-c', 'src.c', '-DNDEBUG']))
        eq(['-UNDEBUG'],
           test(['clang', '-c', 'src.c', '-UNDEBUG']))
        eq(['-Dvar1=val1', '-Dvar2=val2'],
           test(['clang', '-c', 'src.c', '-Dvar1=val1', '-Dvar2=val2']))
        eq(['-Dvar="val ues"'],
           test(['clang', '-c', 'src.c', '-Dvar="val ues"']))

    def test_ignored_flags(self):
        def test(cmd):
            salt = ['-I.', '-D_THIS']
            opts = sut.parse({'command': cmd + salt}, lambda x: x)
            self.assertEqual(salt, opts.get('compile_options'))
            return opts.get('link_options', [])

        eq = self.assertEqual

        eq([],
           test(['clang', 'src.o']))
        eq([],
           test(['clang', 'src.o', '-lrt', '-L/opt/company/lib']))
        eq([],
           test(['clang', 'src.o', '-framework', 'foo']))

    def test_compile_only_flags(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            self.assertEqual(None, opts.get('link_options'))
            return opts.get('compile_options', [])

        eq = self.assertEqual

        eq([], test(['clang', '-c', 'src.c']))
        eq([],
           test(['clang', '-c', 'src.c', '-Wnoexcept']))
        eq([],
           test(['clang', '-c', 'src.c', '-Wall']))
        eq(['-Wno-cpp'],
           test(['clang', '-c', 'src.c', '-Wno-cpp']))
        eq(['-std=C99'],
           test(['clang', '-c', 'src.c', '-std=C99']))
        eq(['-mtune=i386', '-mcpu=i386'],
           test(['clang', '-c', 'src.c', '-mtune=i386', '-mcpu=i386']))
        eq(['-nostdinc'],
           test(['clang', '-c', 'src.c', '-nostdinc']))
        eq(['-isystem', '/image/debian'],
           test(['clang', '-c', 'src.c', '-isystem', '/image/debian']))
        eq(['-iprefix', '/usr/local'],
           test(['clang', '-c', 'src.c', '-iprefix', '/usr/local']))
        eq(['-iquote=me'],
           test(['clang', '-c', 'src.c', '-iquote=me']))
        eq(['-iquote', 'me'],
           test(['clang', '-c', 'src.c', '-iquote', 'me']))

    def test_compile_and_link_flags(self):
        def test(cmd):
            opts = sut.parse({'command': cmd}, lambda x: x)
            return opts.get('compile_options', [])

        eq = self.assertEqual

        eq([],
           test(['clang', '-c', 'src.c', '-fsyntax-only']))
        eq(['-fsinged-char'],
           test(['clang', '-c', 'src.c', '-fsinged-char']))
        eq(['-fPIC'],
           test(['clang', '-c', 'src.c', '-fPIC']))
        eq(['-stdlib=libc++'],
           test(['clang', '-c', 'src.c', '-stdlib=libc++']))
        eq(['--sysroot', '/'],
           test(['clang', '-c', 'src.c', '--sysroot', '/']))
        eq(['-isysroot', '/'],
           test(['clang', '-c', 'src.c', '-isysroot', '/']))
        eq([],
           test(['clang', '-c', 'src.c', '-sectorder', 'a', 'b', 'c']))