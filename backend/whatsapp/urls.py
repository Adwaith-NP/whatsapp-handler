from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from . import views

urlpatterns = [
    path("auth/login/", obtain_auth_token),
    path("auth/me/", views.me_view),
    path("whatsapp/status/", views.status_view),
    path("whatsapp/send/", views.send_view),
    path("gemini/settings/", views.gemini_settings_view),
    path("gemini/test/", views.gemini_test_view),
    path("automation/settings/", views.automation_settings_view),
    path("keys/", views.api_keys_view),
    path("keys/<int:pk>/", views.api_key_detail_view),
    # Public, API-key authenticated. Versioned separately from the portal's own
    # endpoints so it can stay stable for outside callers.
    path("v1/messages/", views.public_send_message_view),
]
