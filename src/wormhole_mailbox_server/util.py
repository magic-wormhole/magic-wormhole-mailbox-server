# No unicode_literals
import json, unicodedata
from binascii import hexlify, unhexlify

def to_bytes(u):
    return unicodedata.normalize("NFC", u).encode("utf-8")
def bytes_to_hexstr(b):
    assert isinstance(b, bytes)
    hexstr = hexlify(b).decode("ascii")
    assert isinstance(hexstr, str)
    return hexstr
def hexstr_to_bytes(hexstr):
    assert isinstance(hexstr, str)
    b = unhexlify(hexstr.encode("ascii"))
    assert isinstance(b, bytes)
    return b
def dict_to_bytes(d):
    assert isinstance(d, dict)
    b = json.dumps(d).encode("utf-8")
    assert isinstance(b, bytes)
    return b
def bytes_to_dict(b):
    assert isinstance(b, bytes)
    d = json.loads(b.decode("utf-8"))
    assert isinstance(d, dict)
    return d
