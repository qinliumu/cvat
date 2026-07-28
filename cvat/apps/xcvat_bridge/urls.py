from django.urls import path

from . import views

urlpatterns = [
    path("xcvat/import", views.ImportView.as_view(), name="xcvat-import"),
    path("xcvat/export", views.ExportView.as_view(), name="xcvat-export"),
    path("xcvat/status/<str:job_id>", views.StatusView.as_view(), name="xcvat-status"),
]
