"""Windows user-bound DPAPI credentials, outside the project and its Docker mount."""
import ctypes
import os
from pathlib import Path
import re


class DataBlob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def secret_path():
    local = os.getenv('LOCALAPPDATA')
    return Path(local) / 'Codix' / 'secrets' / 'avalai-key.dpapi' if local else None


def decrypt_windows(ciphertext):
    """Read the default Windows ConvertFrom-SecureString hex/DPAPI format."""
    try:
        if not isinstance(ciphertext, str) or not 20 <= len(ciphertext) <= 32768 or not re.fullmatch('[0-9a-fA-F]+', ciphertext):
            raise ValueError('Invalid encrypted format')
        raw = bytes.fromhex(ciphertext)
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = DataBlob()
        crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DataBlob), ctypes.POINTER(ctypes.c_wchar_p),
                                              ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                                              ctypes.c_uint32, ctypes.POINTER(DataBlob)]
        crypt32.CryptUnprotectData.restype = ctypes.c_int
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise ValueError('Decryption failed')
        try:
            if not 0 < output.cbData <= 8192:
                raise ValueError('Invalid credential size')
            value = ctypes.string_at(output.pbData, output.cbData).decode('utf-16-le')
            if not re.fullmatch(r'[!-~]{8,4096}', value):
                raise ValueError('Invalid credential')
            return value
        finally:
            ctypes.memset(output.pbData, 0, output.cbData)
            kernel32.LocalFree(output.pbData)
    except Exception:
        raise RuntimeError('Cannot read the private Windows credential. Save it with ConvertFrom-SecureString under the same Windows user.') from None


def load_key():
    # Explicit environment configuration retains compatibility with container-based development.
    value = os.getenv('AVALAI_API_KEY') or os.getenv('OPENAI_API_KEY')
    if value:
        if not re.fullmatch(r'[!-~]{8,4096}', value):
            raise RuntimeError('Invalid API credential format.')
        return value
    if os.name != 'nt':
        return ''  # Never mount a Windows credential store into a project container.
    path = secret_path()
    if path is None or not path.exists():
        return ''
    for item in [path, *list(path.parents)[:2]]:
        info = item.lstat()
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Credential store links/reparse points are blocked.')
    if path.stat().st_size > 32768:
        raise RuntimeError('Invalid encrypted credential size.')
    return decrypt_windows(path.read_text(encoding='ascii').strip())
