"""智慧树纯协议认证的离线测试。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from logic.zhihuishu import api
from logic.zhihuishu.models import (
    ZhsAuthError,
    ZhsCaptchaError,
    ZhsExtraAuthRequired,
    ZhsSmsRequired,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, BaseException):
            raise self._body
        return self._body


class FakeSession:
    """只实现认证函数使用的最小会话接口，不产生网络请求。"""

    def __init__(self, responses=None, cookies=None):
        self.session = SimpleNamespace(headers={})
        self.cookies = cookies if cookies is not None else {}
        self.responses = list(responses or [])
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "login" in url and kwargs.get("params"):
            self.cookies["CASLOGC"] = "fake-session"
        return self.responses.pop(0) if self.responses else FakeResponse()

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0) if self.responses else FakeResponse()


class TestResponseHelpers(unittest.TestCase):
    def test_nested_status_and_credentials(self):
        body = {"data": {"result": {"status": "0", "uuid": "u", "pwd": "p"}}}
        self.assertEqual(api._status_code(body), 0)
        self.assertEqual(api._nested_response_value(body, "uuid"), "u")
        self.assertEqual(api._nested_response_value(body, "pwd"), "p")

    def test_bool_parser(self):
        self.assertTrue(api._as_bool("true"))
        self.assertTrue(api._as_bool("1"))
        self.assertFalse(api._as_bool("false"))
        self.assertFalse(api._as_bool("0"))


class TestPasswordLogin(unittest.TestCase):
    def _run_status(self, status):
        session = FakeSession()
        with patch.object(api, "_api_query", return_value={"status": str(status)}):
            api.login_password(session, "account", "password")

    def test_invalid_credentials(self):
        with self.assertRaises(ZhsAuthError):
            self._run_status(-2)

    def test_captcha_required(self):
        with self.assertRaises(ZhsCaptchaError):
            self._run_status(-4)

    def test_sms_required(self):
        with self.assertRaises(ZhsSmsRequired):
            self._run_status(-9)

    def test_missing_one_time_credentials(self):
        with self.assertRaises(ZhsAuthError):
            self._run_status(0)

    def test_extra_auth_required(self):
        session = FakeSession()
        with patch.object(api, "_api_query", side_effect=[
            {"data": {"status": "0", "uuid": "u", "pwd": "p"}},
            {"rt": {"needAuth": "true"}},
        ]):
            with self.assertRaises(ZhsExtraAuthRequired):
                api.login_password(session, "account", "password")

    def test_success_with_nested_response(self):
        session = FakeSession()
        with patch.object(api, "_api_query", side_effect=[
            {"data": {"result": {"status": "0", "uuid": "u", "pwd": "p"}}},
            {"rt": {"needAuth": False}},
        ]):
            api.login_password(session, "account", "password")
        self.assertIn("CASLOGC", session.cookies)
        self.assertEqual(len(session.calls), 2)


class TestSessionValidation(unittest.TestCase):
    def test_valid_session(self):
        body = { 
            "success": True,
            "data": {"userId": "user-1"},
        }
        session = FakeSession([FakeResponse(body=body), FakeResponse(body=body)],
                              cookies={"CASLOGC": "fake"})
        result = api.validate_session_detail(session)
        self.assertEqual(result.status, "LOGIN_SUCCESS")
        self.assertEqual(result.user_id, "user-1")
        self.assertTrue(api.validate_session(session))

    def test_expired_session(self):
        session = FakeSession([FakeResponse(401, {"code": 401})])
        result = api.validate_session_detail(session)
        self.assertEqual(result.status, "TOKEN_EXPIRED")
        self.assertFalse(api.validate_session(session))

    def test_network_failure(self):
        import requests

        session = FakeSession([requests.RequestException("offline")])

        def raise_request(*_args, **_kwargs):
            raise requests.RequestException("offline")

        session.get = raise_request
        result = api.validate_session_detail(session)
        self.assertEqual(result.status, "NETWORK_ERROR")


if __name__ == "__main__":
    unittest.main()