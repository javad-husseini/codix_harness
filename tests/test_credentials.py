import ctypes
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.credentials import DataBlob, decrypt_windows, load_key, secret_path
from backend.provider import AVALAI_URL, Budget, BudgetExceeded, ResponsesProvider


class CredentialTests(unittest.TestCase):
    def test_environment_precedence_and_validation(self):
        with patch.dict(os.environ, {'AVALAI_API_KEY': 'fixture-avalai', 'OPENAI_API_KEY': 'fixture-openai'}, clear=True):
            self.assertEqual(load_key(), 'fixture-avalai')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-openai'}, clear=True):
            self.assertEqual(load_key(), 'fixture-openai')
        with patch.dict(os.environ, {'AVALAI_API_KEY': 'bad\nsecret'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, '^Invalid API credential format'):
                load_key()

    def test_fixed_store_and_no_linux_file_fallback(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': '/private/user'}, clear=True):
            self.assertEqual(str(secret_path()), '/private/user/Codix/secrets/avalai-key.dpapi')
            with patch('backend.credentials.decrypt_windows') as decrypt:
                self.assertEqual(load_key(), '')
                decrypt.assert_not_called()

    def test_dpapi_utf16_and_native_buffer_cleanup(self):
        raw = 'fixture-private-key'.encode('utf-16-le')
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)

        def unprotect(source, description, entropy, reserved, prompt, flags, output):
            self.assertEqual(flags, 1)
            blob = ctypes.cast(output, ctypes.POINTER(DataBlob)).contents
            blob.cbData = len(raw)
            blob.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            return 1

        free = Mock()
        crypt = SimpleNamespace(CryptUnprotectData=Mock(side_effect=unprotect))
        kernel = SimpleNamespace(LocalFree=free)
        with patch.object(ctypes, 'WinDLL', create=True, side_effect=[crypt, kernel]):
            self.assertEqual(decrypt_windows('01' * 20), 'fixture-private-key')
        self.assertEqual(bytes(buffer), bytes(len(raw)))
        free.assert_called_once()

    def test_bad_ciphertext_has_generic_error(self):
        with self.assertRaisesRegex(RuntimeError, '^Cannot read the private Windows credential'):
            decrypt_windows('not-a-key')


class AvalAITests(unittest.TestCase):
    def provider(self, model='gpt-test'):
        return ResponsesProvider(model, 'fixture-private-key', AVALAI_URL)

    def test_default_and_origin_allowlist(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ResponsesProvider('gpt-test', 'fixture-private-key').base_url, AVALAI_URL)
        for url in ['http://api.avalai.ir/v1', 'https://evil.test/v1',
                    'https://user@api.avalai.ir/v1', AVALAI_URL + '?x=1']:
            with self.assertRaises(RuntimeError):
                ResponsesProvider('gpt-test', 'fixture-private-key', url)

    def test_estimate_reserves_before_send_without_count_endpoint(self):
        provider = self.provider()
        budget = Budget()

        def post(endpoint, payload):
            self.assertEqual(endpoint, 'responses')
            self.assertGreater(budget.used, 6144)
            self.assertEqual(payload['max_output_tokens'], 2048)
            return {'status': 'completed', 'output': [
                {'type': 'function_call', 'name': 'set_plan', 'arguments': '{}'}]}

        provider._post = Mock(side_effect=post)
        self.assertEqual(provider.call('instructions', {}, [], budget), ('set_plan', {}))
        provider._post.assert_called_once()
        self.assertGreater(budget.used, 6144)  # Missing usage keeps the reservation.

    def test_budget_and_unsupported_model_block_network(self):
        for model, used, error in [('gpt-test', 24000, BudgetExceeded), ('other-model', 0, RuntimeError)]:
            provider = self.provider(model)
            provider._post = Mock()
            budget = Budget()
            budget.used = used
            with self.assertRaises(error):
                provider.call('instructions', {}, [], budget)
            provider._post.assert_not_called()
