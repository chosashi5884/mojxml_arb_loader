# defusedxml - ElementTree
#
# Copyright (c) 2013 by Christian Heimes <christian@python.org>
# Licensed to PSF under a Contributor Agreement.
# See https://www.python.org/psf/license for licensing details.
#
# Vendored copy (0.7.1) bundled with MOJ Arbitrary Coord Loader plugin.
# Source: https://github.com/tiran/defusedxml
#
"""defusedxml - safe xml.etree.ElementTree replacements

Python バージョン互換のため XMLParser サブクラス方式を採用。
parser.parser (expat内部属性) には依存しない。
"""

import re
import xml.etree.ElementTree as _ET
from xml.etree.ElementTree import XMLParser, ParseError

from . import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden

# DOCTYPE / ENTITY の検出パターン（バイト列・文字列両対応）
_RE_DOCTYPE = re.compile(rb'<!DOCTYPE', re.IGNORECASE)
_RE_ENTITY  = re.compile(rb'<!ENTITY',  re.IGNORECASE)


def _pre_scan(data):
    """
    パース前に危険なXMLコンストラクトをバイト列レベルで検出する。
    XMLParser サブクラスのみでは捕捉できないケースへの多重防御。
    """
    if isinstance(data, str):
        data = data.encode('utf-8', errors='replace')
    if _RE_DOCTYPE.search(data):
        raise DTDForbidden('DOCTYPE', None, None)
    if _RE_ENTITY.search(data):
        raise EntitiesForbidden('ENTITY', None, None, None, None, None)


class _SafeXMLParser(XMLParser):
    """
    DTD・外部参照を禁止する安全な XMLParser サブクラス。
    doctype() メソッドのオーバーライドで DTD 検出時に例外を送出する。
    (Python 3.8+ で利用可能な公式 API)
    """

    def doctype(self, name, pubid, system):
        raise DTDForbidden(name, system, pubid)


def fromstring(text, forbid_dtd=True, forbid_entities=True,
               forbid_external=True):
    """
    Safe version of xml.etree.ElementTree.fromstring().

    Parses an XML section from a string constant and returns an Element.
    Raises DTDForbidden or EntitiesForbidden if the document contains
    DTDs or entity definitions.
    """
    # バイト列レベルの事前チェック（多重防御）
    if forbid_dtd or forbid_entities:
        _pre_scan(text)

    parser = _SafeXMLParser()
    parser.feed(text)
    return parser.close()


def parse(source, parser=None, forbid_dtd=True, forbid_entities=True,
          forbid_external=True):
    """Safe version of xml.etree.ElementTree.parse()."""
    if parser is None:
        parser = _SafeXMLParser()
    return _ET.parse(source, parser=parser)


def iterparse(source, events=None, parser=None, forbid_dtd=True,
              forbid_entities=True, forbid_external=True):
    """Safe version of xml.etree.ElementTree.iterparse()."""
    if parser is None:
        parser = _SafeXMLParser()
    return _ET.iterparse(source, events=events, parser=parser)
