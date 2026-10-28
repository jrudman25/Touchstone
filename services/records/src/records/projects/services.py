"""Creation path for immutable PromptVersions.

This is the only supported way to create a version; the admin add form and
the later API both call create_prompt_version so number and variables are
always server-assigned.
"""

from django.db import transaction
from django.db.models import Max

from .models import PromptTemplate, PromptVersion
from .variables import extract_variables


def create_prompt_version(
    template: PromptTemplate,
    *,
    system_message: str,
    body: str,
) -> PromptVersion:
    """Create the next immutable version of a template.

    Number allocation is serialized by locking the parent template row inside
    a transaction, so concurrent creates cannot collide on (template, number).
    """
    with transaction.atomic():
        locked_template = PromptTemplate.objects.select_for_update().get(pk=template.pk)
        highest = (
            PromptVersion.objects.filter(template=locked_template).aggregate(highest=Max("number"))[
                "highest"
            ]
            or 0
        )
        version = PromptVersion(
            template=locked_template,
            number=highest + 1,
            system_message=system_message,
            body=body,
            variables=extract_variables(system_message, body),
        )
        version.save()
    return version
