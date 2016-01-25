# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from bgfiles.http import create_content_disposition
from django.test import SimpleTestCase


class CreateContentDispositionTest(SimpleTestCase):

    def test(self):
        header = create_content_disposition('Fußball.pdf')
        self.assertEqual(b'attachment; filename="Fuball.pdf"; filename*=UTF-8\'\'Fu%C3%9Fball.pdf', header)
        header = create_content_disposition('Fußball.pdf', attachment=False)
        self.assertEqual(b'inline; filename="Fuball.pdf"; filename*=UTF-8\'\'Fu%C3%9Fball.pdf', header)
        header = create_content_disposition(b'Fussball.pdf')
        self.assertEqual(b'attachment; filename="Fussball.pdf"', header)
        header = create_content_disposition(b'Fussball.pdf', attachment=False)
        self.assertEqual(b'inline; filename="Fussball.pdf"', header)
        expected = (b'attachment; filename="Leery  Jenkins  My Man .pdf"; '
                    b'filename*=UTF-8\'\'L%C3%A9%C3%ABr%C5%93%C3%B8y%20%20Jenkins%20%20My%20Man%20.pdf')
        self.assertEqual(create_content_disposition('Léërœøy \\Jenkins/"My Man".pdf'), expected)
        expected = (b'inline; filename="Leery  Jenkins  My Man .pdf"; '
                    b'filename*=UTF-8\'\'L%C3%A9%C3%ABr%C5%93%C3%B8y%20%20Jenkins%20%20My%20Man%20.pdf')
        self.assertEqual(create_content_disposition('Léërœøy \\Jenkins/"My Man".pdf', attachment=False), expected)
