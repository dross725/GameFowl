from django.urls import path
from SmartWagers.consumers import WagersConsumer
from SmartWagers.print_jobs_consumer import PrintJobsConsumer

websocket_urlpatterns = [
    path("ws/index/", WagersConsumer.as_asgi()),
    path("ws/user/", WagersConsumer.as_asgi()),
    path("ws/administrator/", WagersConsumer.as_asgi()),
    path('ws/SmartWagers/', WagersConsumer.as_asgi()),
    path('ws/print-jobs/', PrintJobsConsumer.as_asgi()),
]

# from django.urls import path
# from . import consumers

# websocket_urlpatterns = [
#     path('ws/SmartWagers/', consumers.WagersConsumer.as_asgi()),
# ]