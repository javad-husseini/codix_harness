import ctypes
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import ssl

from backend.credentials import DataBlob, decrypt_windows, load_key, secret_path
from backend.provider import AVALAI_URL, Budget, BudgetExceeded, ResponsesProvider, ProviderError


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
    def test_direct_route_is_scoped_to_exact_avalai_origin(self):
        with patch('backend.provider.urllib.request.build_opener') as build:
            self.provider()
        proxy = [handler for handler in build.call_args.args if isinstance(handler, urllib.request.ProxyHandler)]
        self.assertEqual(len(proxy), 1)
        self.assertEqual(proxy[0].proxies, {})
        with patch('backend.provider.urllib.request.build_opener') as build:
            ResponsesProvider('gpt-test', 'fixture-private-key', 'https://api.openai.com/v1')
        self.assertFalse(any(isinstance(handler, urllib.request.ProxyHandler) for handler in build.call_args.args))

    def test_tls_diagnostic_only_accepts_numeric_codes_and_known_reason_labels(self):
        message = str(ProviderError('tls', 20, 'CERTIFICATE_VERIFY_FAILED'))
        self.assertIn('20', message)
        self.assertIn('CERTIFICATE_VERIFY_FAILED', message)
        message = str(ProviderError('tls', 'fixture-private-key', 'fixture-private-key'))
        self.assertNotIn('fixture-private-key', message)

    def test_tls_context_has_public_roots_and_requires_verified_hostname(self):
        with patch('backend.provider.urllib.request.build_opener') as build:
            self.provider()
        context = build.call_args.args[1]._context
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(len(context.get_ca_certs()), 0)

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

    def test_http_diagnostics_are_fixed_and_never_echo_body_or_headers(self):
        for status, expected in [(400, 'request'), (401, 'authentication'), (403, 'permission'),
                                 (404, 'not_found'), (429, 'rate_limit'), (503, 'server')]:
            provider = self.provider()
            error = urllib.error.HTTPError(AVALAI_URL, status, 'fixture-private-key',
                {'Authorization': 'fixture-private-key'}, io.BytesIO(b'{"error":{"message":"fixture-private-key"}}'))
            provider.opener = Mock()
            provider.opener.open.side_effect = error
            with self.assertRaises(ProviderError) as caught:
                provider._post('responses', {})
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn('fixture-private-key', str(caught.exception))
            provider.opener.open.assert_called_once()

    def test_quota_and_tls_classification_without_raw_errors(self):
        for error, expected in [
            (urllib.error.HTTPError(AVALAI_URL, 429, 'secret', {}, io.BytesIO(json.dumps({'error': {'code': 'insufficient_quota', 'message': 'fixture-private-key'}}).encode())), 'quota'),
            (urllib.error.URLError(ssl.SSLCertVerificationError('fixture-private-key')), 'tls'),
            (urllib.error.URLError(ssl.SSLError('fixture-private-key')), 'tls_protocol'),
            (urllib.error.URLError('fixture-private-key'), 'network'),
        ]:
            provider = self.provider()
            provider.opener = Mock()
            provider.opener.open.side_effect = error
            with self.assertRaises(ProviderError) as caught:
                provider._post('responses', {})
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn('fixture-private-key', str(caught.exception))
