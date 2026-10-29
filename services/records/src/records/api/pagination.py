"""Pagination for the records API."""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Page-number pagination with a client-adjustable page size."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
