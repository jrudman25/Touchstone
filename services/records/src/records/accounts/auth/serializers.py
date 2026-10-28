"""Request/response serializers for the auth views.

TokenObtainRequestSerializer validates the obtain body at runtime; the rest
describe request/response shapes for OpenAPI schema generation.
"""

from typing import Any

from rest_framework import serializers


class TokenObtainRequestSerializer(serializers.Serializer[Any]):
    username = serializers.CharField()
    password = serializers.CharField()


class AccessTokenSerializer(serializers.Serializer[Any]):
    access = serializers.CharField()


class DetailSerializer(serializers.Serializer[Any]):
    detail = serializers.CharField()


class MeOrganizationSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    role = serializers.CharField()


class MeSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    username = serializers.CharField()
    organizations = MeOrganizationSerializer(many=True)
