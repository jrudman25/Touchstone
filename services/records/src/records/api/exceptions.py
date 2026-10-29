"""API exceptions used by the records viewsets."""

from rest_framework import status
from rest_framework.exceptions import APIException


class Conflict(APIException):
    """409 response for writes rejected because of related records or state."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"
