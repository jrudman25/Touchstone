"""Admin registrations for the projects app."""

from django.contrib import admin
from django.http import HttpRequest

from .models import Dataset, Project, PromptTemplate, PromptVersion
from .services import create_prompt_version


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "organization")
    list_filter = ("organization",)
    search_fields = ("name",)


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "project")
    search_fields = ("name",)


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "row_count")
    # row_count is set by FastAPI through a dedicated API action, never edited.
    readonly_fields = ("row_count",)


@admin.register(PromptVersion)
class PromptVersionAdmin(admin.ModelAdmin):
    """View-only for saved versions; adding creates a new immutable version."""

    add_fields = ("template", "system_message", "body")
    view_fields = ("template", "number", "system_message", "body", "variables", "created_at")
    list_display = ("template", "number", "created_at")

    def get_fields(self, request: HttpRequest, obj: PromptVersion | None = None) -> tuple[str, ...]:
        return self.view_fields if obj is not None else self.add_fields

    def get_readonly_fields(
        self, request: HttpRequest, obj: PromptVersion | None = None
    ) -> tuple[str, ...]:
        return self.view_fields if obj is not None else ()

    def has_change_permission(self, request: HttpRequest, obj: PromptVersion | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PromptVersion | None = None) -> bool:
        return False

    def save_model(
        self, request: HttpRequest, obj: PromptVersion, form: object, change: bool
    ) -> None:
        version = create_prompt_version(
            obj.template, system_message=obj.system_message, body=obj.body
        )
        # Point obj at the created row so the admin LogEntry and the post-add
        # redirect refer to the real version.
        obj.pk = version.pk
        obj.number = version.number
        obj.variables = version.variables
        obj.created_at = version.created_at
        obj._state.adding = False
        obj._state.db = version._state.db
