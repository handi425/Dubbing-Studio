"""Shared local OpenRouter settings; keys protected by Windows DPAPI."""
import base64
import ctypes
import json
from pathlib import Path
from runtime_paths import DATA

def user_settings_path():
    return DATA / 'settings.json'


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def protect_secret(secret, unprotect=False):
    raw = base64.b64decode(secret) if unprotect else secret.encode('utf-8')
    source_buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    function = ctypes.windll.crypt32.CryptUnprotectData if unprotect else ctypes.windll.crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar),
                         ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_uint32, ctypes.POINTER(_DataBlob)]
    function.restype = ctypes.c_int
    if unprotect:
        ok = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise ValueError('Windows tidak dapat membuka kunci OpenRouter yang tersimpan.')
    try:
        result = ctypes.string_at(target.pbData, target.cbData)
        return result.decode('utf-8') if unprotect else base64.b64encode(result).decode('ascii')
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(target.pbData)


def read_user_settings(path=None):
    path = Path(path) if path is not None else user_settings_path()
    if not path.is_file():
        return {'openrouter_key': '', 'openrouter_model': 'openrouter/free'}
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'openrouter_key': '', 'openrouter_model': 'openrouter/free'}
    key = value.get('openrouter_key', '')
    if value.get('openrouter_key_dpapi'):
        key = protect_secret(value['openrouter_key_dpapi'], unprotect=True)
    return {'openrouter_key': key,
            'openrouter_model': value.get('openrouter_model', 'openrouter/free')}
