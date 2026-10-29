"""Seed the local development records: superuser, dev org, and mock provider.

Reads the superuser credentials from DEV_SUPERUSER_USERNAME and
DEV_SUPERUSER_PASSWORD and is safe to run twice. Never prints the password.
"""

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from records.accounts.models import Membership, Organization, User
from records.projects.models import Project
from records.providers.models import ModelConfig, ProviderConfig


class Command(BaseCommand):
    help = "Create the dev superuser, organization, project, and mock provider/model."

    def handle(self, *args: Any, **options: Any) -> None:
        username = os.environ.get("DEV_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DEV_SUPERUSER_PASSWORD", "")
        if not username or not password.strip():
            raise CommandError(
                "DEV_SUPERUSER_USERNAME and DEV_SUPERUSER_PASSWORD must both be set."
            )

        with transaction.atomic():
            user, user_created = User.objects.get_or_create(username=username)
            if user_created:
                user.set_password(password)
            changed = False
            if not user.is_staff:
                user.is_staff = True
                changed = True
            if not user.is_superuser:
                user.is_superuser = True
                changed = True
            if user_created or changed:
                user.save()
            if user_created:
                self.stdout.write(f"created user {username}")
            elif changed:
                self.stdout.write(f"updated user {username}")
            else:
                self.stdout.write(f"exists user {username}")

            organization, org_created = Organization.objects.get_or_create(
                slug="dev", defaults={"name": "Dev Organization"}
            )
            self.stdout.write(
                f"{'created' if org_created else 'exists'} organization {organization.slug}"
            )

            membership, membership_created = Membership.objects.get_or_create(
                user=user,
                organization=organization,
                defaults={"role": Membership.Role.OWNER},
            )
            if membership_created:
                self.stdout.write(f"created membership {username}@{organization.slug} (owner)")
            elif membership.role != Membership.Role.OWNER:
                membership.role = Membership.Role.OWNER
                membership.save()
                self.stdout.write(f"updated membership {username}@{organization.slug} (owner)")
            else:
                self.stdout.write(f"exists membership {username}@{organization.slug} (owner)")

            project, project_created = Project.objects.get_or_create(
                organization=organization, name="Demo project"
            )
            self.stdout.write(
                f"{'created' if project_created else 'exists'} project {project.name}"
            )

            provider, provider_created = ProviderConfig.objects.get_or_create(
                organization=organization,
                name="Mock",
                defaults={"kind": ProviderConfig.Kind.MOCK, "base_url": ""},
            )
            self.stdout.write(
                f"{'created' if provider_created else 'exists'} provider {provider.name}"
            )

            model, model_created = ModelConfig.objects.get_or_create(
                provider=provider,
                model_name="mock-echo",
                defaults={
                    "temperature": 0,
                    "max_tokens": 512,
                    "context_length": 8192,
                    "input_price_per_1k": 0,
                    "output_price_per_1k": 0,
                },
            )
            self.stdout.write(
                f"{'created' if model_created else 'exists'} model {model.model_name}"
            )
