# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from shutil import rmtree
from tempfile import mkdtemp


class WithTempDir(object):
    tempdir = None

    @classmethod
    def setUpClass(cls):
        super(WithTempDir, cls).setUpClass()
        cls.tempdir = mkdtemp()

    @classmethod
    def tearDownClass(cls):
        if cls.tempdir:
            rmtree(cls.tempdir)
        super(WithTempDir, cls).tearDownClass()
