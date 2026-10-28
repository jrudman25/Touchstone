"""Refresh token construction.

The org role map is always rebuilt from current Membership rows so role
changes take effect at the next refresh; it is never copied from an old
token. The access token inherits the map via simplejwt's claim copying.
"""

from rest_framework_simplejwt.tokens import RefreshToken

from records.accounts.models import User

from .constants import ORGS_CLAIM


def build_refresh_token(user: User) -> RefreshToken:
    """Mint a refresh token carrying the user's current org roles."""
    refresh = RefreshToken.for_user(user)
    refresh[ORGS_CLAIM] = {
        str(membership.organization_id): membership.role for membership in user.memberships.all()
    }
    return refresh
