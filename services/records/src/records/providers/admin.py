"""Admin registrations for the providers app."""

from django.contrib import admin

from .models import ModelConfig, ProviderConfig, ScorerConfig


@admin.register(ProviderConfig)
class ProviderConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "kind", "max_concurrency")
    list_filter = ("kind", "organization")


@admin.register(ModelConfig)
class ModelConfigAdmin(admin.ModelAdmin):
    list_display = ("model_name", "provider", "max_tokens", "context_length")


@admin.register(ScorerConfig)
class ScorerConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "kind")
    list_filter = ("kind",)
