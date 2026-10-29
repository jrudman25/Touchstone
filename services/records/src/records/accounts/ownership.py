"""The "an organization must keep at least one owner" invariant.

Shared by the memberships API (the authoritative locked check), the model's
``clean()`` (demotion validation), and Django admin (delete protection).
"""

from collections.abc import Iterable

from django.db import transaction

from records.accounts.models import Membership

LAST_OWNER_MESSAGE = "An organization must keep at least one owner."


def is_last_owner(membership: Membership) -> bool:
    """True if ``membership`` is its organization's only owner row.

    Locks the org's owner rows (``select_for_update``) before reading them.
    Runs in its own ``transaction.atomic`` so it is safe to call with or
    without an outer transaction; when there is one, the lock is held until
    the outer transaction ends.
    """
    if membership.pk is None:
        return False
    with transaction.atomic():
        owner_ids = list(
            Membership.objects.select_for_update()
            .filter(
                organization_id=membership.organization_id,
                role=Membership.Role.OWNER,
            )
            .values_list("id", flat=True)
        )
    return membership.pk in owner_ids and len(owner_ids) == 1


def memberships_leaving_orgs_ownerless(
    memberships: Iterable[Membership],
) -> list[Membership]:
    """Owner rows in ``memberships`` whose organization keeps zero owners.

    An organization is orphaned when every one of its owner rows is in the
    set being deleted. Used to block membership bulk deletes and user deletes.
    Same locking pattern as :func:`is_last_owner`.
    """
    deleted = list(memberships)
    if not deleted:
        return []
    deleted_ids = {m.pk for m in deleted}
    org_ids = {m.organization_id for m in deleted}
    with transaction.atomic():
        owners_by_org: dict[int, set[int]] = {org_id: set() for org_id in org_ids}
        owner_rows = (
            Membership.objects.select_for_update()
            .filter(organization_id__in=org_ids, role=Membership.Role.OWNER)
            .values_list("id", "organization_id")
        )
        for owner_id, org_id in owner_rows:
            owners_by_org[org_id].add(owner_id)
    orphaned = {org_id for org_id, ids in owners_by_org.items() if ids <= deleted_ids}
    return [m for m in deleted if m.role == Membership.Role.OWNER and m.organization_id in orphaned]
