"""
Tests for the throttling implementations in the permissions module.
"""
from __future__ import unicode_literals
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test.client import RequestFactory
from rest_framework.authentication import BasicAuthentication, \
    SessionAuthentication, TokenAuthentication
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from rest_framework.response import Response
from django.conf.urls import patterns


class User3SecRateThrottle(UserRateThrottle):
    rate = '3/sec'
    scope = 'seconds'


class User3MinRateThrottle(UserRateThrottle):
    rate = '3/min'
    scope = 'minutes'


class MockView(APIView):
    throttle_classes = (User3SecRateThrottle,)

    def get(self, request):
        return Response('foo')


class MockView_MinuteThrottling(APIView):
    throttle_classes = (User3MinRateThrottle,)

    def get(self, request):
        return Response('foo')


class ThrottlingTests(TestCase):
    urls = 'rest_framework.tests.throttling'

    def setUp(self):
        """
        Reset the cache so that no throttles will be active
        """
        cache.clear()
        self.factory = RequestFactory()

    def test_requests_are_throttled(self):
        """
        Ensure request rate is limited
        """
        request = self.factory.get('/')
        for dummy in range(4):
            response = MockView.as_view()(request)
        self.assertEqual(429, response.status_code)

    def set_throttle_timer(self, view, value):
        """
        Explicitly set the timer, overriding time.time()
        """
        view.throttle_classes[0].timer = lambda self: value

    def test_request_throttling_expires(self):
        """
        Ensure request rate is limited for a limited duration only
        """
        self.set_throttle_timer(MockView, 0)

        request = self.factory.get('/')
        for dummy in range(4):
            response = MockView.as_view()(request)
        self.assertEqual(429, response.status_code)

        # Advance the timer by one second
        self.set_throttle_timer(MockView, 1)

        response = MockView.as_view()(request)
        self.assertEqual(200, response.status_code)

    def ensure_is_throttled(self, view, expect):
        request = self.factory.get('/')
        request.user = User.objects.create(username='a')
        for dummy in range(3):
            view.as_view()(request)
        request.user = User.objects.create(username='b')
        response = view.as_view()(request)
        self.assertEqual(expect, response.status_code)

    def test_request_throttling_is_per_user(self):
        """
        Ensure request rate is only limited per user, not globally for
        PerUserThrottles
        """
        self.ensure_is_throttled(MockView, 200)

    def ensure_response_header_contains_proper_throttle_field(self, view, expected_headers):
        """
        Ensure the response returns an X-Throttle field with status and next attributes
        set properly.
        """
        request = self.factory.get('/')
        for timer, expect in expected_headers:
            self.set_throttle_timer(view, timer)
            response = view.as_view()(request)
            if expect is not None:
                self.assertEqual(response['X-Throttle-Wait-Seconds'], expect)
            else:
                self.assertFalse('X-Throttle-Wait-Seconds' in response)

    def test_seconds_fields(self):
        """
        Ensure for second based throttles.
        """
        self.ensure_response_header_contains_proper_throttle_field(MockView,
         ((0, None),
          (0, None),
          (0, None),
          (0, '1')
         ))

    def test_minutes_fields(self):
        """
        Ensure for minute based throttles.
        """
        self.ensure_response_header_contains_proper_throttle_field(MockView_MinuteThrottling,
         ((0, None),
          (0, None),
          (0, None),
          (0, '60')
         ))

    def test_next_rate_remains_constant_if_followed(self):
        """
        If a client follows the recommended next request rate,
        the throttling rate should stay constant.
        """
        self.ensure_response_header_contains_proper_throttle_field(MockView_MinuteThrottling,
         ((0, None),
          (20, None),
          (40, None),
          (60, None),
          (80, None)
         ))


class Anon3SecRateThrottle(AnonRateThrottle):
    rate = '3/sec'
    scope = 'seconds'


class NextMockView(APIView):
    throttle_classes = (Anon3SecRateThrottle,)

    def get(self, request):
        return Response('foo')


urlpatterns = patterns('',
    (r'^basic/$', NextMockView.as_view(authentication_classes=[BasicAuthentication])),
    (r'^session/$', NextMockView.as_view(authentication_classes=[SessionAuthentication])),
    (r'^token/$', NextMockView.as_view(authentication_classes=[TokenAuthentication])),
    (r'^combined/$', NextMockView.as_view(authentication_classes=[SessionAuthentication, BasicAuthentication])),
    (r'^combined/reverse/$', NextMockView.as_view(authentication_classes=[SessionAuthentication, BasicAuthentication])),
)


class ThrottlingWithAuthenticationTest(TestCase):
    urls = 'rest_framework.tests.throttling'

    def setUp(self):
        self.username = 'john'
        self.email = 'lennon@thebeatles.com'
        self.password = 'password'
        self.user = User.objects.create_user(self.username, self.email, self.password)

    def test_basic_auth(self):
        auth = 'Basic wrongcreds'
        response = self.client.get('/basic/', HTTP_AUTHORIZATION=auth)
        self.assertEqual(response.status_code, 200)

    def test_session_auth(self):
        response = self.client.get('/session/')
        self.assertEqual(response.status_code, 200)

    def test_token_auth(self):
        auth = 'Token wrongone'
        response = self.client.get('/token/', HTTP_AUTHORIZATION=auth)
        self.assertEqual(response.status_code, 200)

    def test_combined_auth(self):
        auth = 'Basic wrongcreds'
        response = self.client.get('/combined/', HTTP_AUTHORIZATION=auth)
        self.assertEqual(response.status_code, 200)

    def test_combined_reverse_auth(self):
        auth = 'Basic wrongcreds'
        response = self.client.get('/combined/', HTTP_AUTHORIZATION=auth)
        self.assertEqual(response.status_code, 200)
