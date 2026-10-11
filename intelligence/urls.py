from django.urls import path

from intelligence import api

urlpatterns = [path("recommendations/", api.recommend, name="recommendations")]
