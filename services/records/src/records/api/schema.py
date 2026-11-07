"""drf-spectacular schema glue for shared viewset conventions."""

from typing import Any

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework.serializers import Serializer


class RecordsAutoSchema(AutoSchema):
    """Documents each viewset's ``filter_params`` on the list action."""

    def get_override_parameters(
        self,
    ) -> list[OpenApiParameter | Serializer[Any] | type[Serializer[Any]]]:
        parameters: list[OpenApiParameter | Serializer[Any] | type[Serializer[Any]]] = (
            super().get_override_parameters()
        )
        view = self.view
        if getattr(view, "action", None) != "list":
            return parameters
        filter_params: dict[str, str] = getattr(view, "filter_params", {})
        for param in filter_params:
            parameters.append(
                OpenApiParameter(
                    param,
                    OpenApiTypes.INT,
                    description=f"Only records with this {param} id.",
                )
            )
        return parameters
