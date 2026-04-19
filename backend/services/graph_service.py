"""
M365 Guardian — Microsoft Graph API Service.
Handles all interactions with Entra ID and Exchange Online via Graph API.
"""

import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.identity import ClientSecretCredential
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.models.user import User
from msgraph.generated.models.password_profile import PasswordProfile
from msgraph.generated.models.assigned_license import AssignedLicense
from msgraph.generated.users.users_request_builder import UsersRequestBuilder
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.generated.users.item.assign_license.assign_license_post_request_body import (
    AssignLicensePostRequestBody,
)

from backend.config import config

logger = logging.getLogger(__name__)


class GraphService:
    """Wrapper around Microsoft Graph SDK for M365 Guardian operations."""

    def __init__(self):
        self._credential = ClientSecretCredential(
            tenant_id=config.azure_ad.tenant_id,
            client_id=config.azure_ad.client_id,
            client_secret=config.azure_ad.client_secret,
        )
        self._client = GraphServiceClient(
            self._credential,
            scopes=["https://graph.microsoft.com/.default"],
        )

    # ── USER SEARCH ──────────────────────────────────────────────────

    async def search_users(
        self,
        query: str,
        odata_filter: str | None = None,
        select: list[str] | None = None,
        top: int = 10,
    ) -> list[dict]:
        """Search users by displayName, mail, or UPN."""
        select = select or [
            "id", "displayName", "userPrincipalName", "mail",
            "accountEnabled", "department", "jobTitle",
        ]

        try:
            if odata_filter:
                params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                    filter=odata_filter,
                    select=select,
                    top=top,
                    count=True,
                )
                config = RequestConfiguration(query_parameters=params)
                config.headers.add("ConsistencyLevel", "eventual")
                result = await self._client.users.get(request_configuration=config)
            else:
                # Use $search for free-text search
                params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                    search=f'"displayName:{query}" OR "mail:{query}" OR "userPrincipalName:{query}"',
                    select=select,
                    top=top,
                    count=True,
                )
                config = RequestConfiguration(query_parameters=params)
                config.headers.add("ConsistencyLevel", "eventual")
                result = await self._client.users.get(request_configuration=config)

            users = []
            if result and result.value:
                for u in result.value:
                    users.append({
                        "id": u.id,
                        "displayName": u.display_name,
                        "userPrincipalName": u.user_principal_name,
                        "mail": u.mail,
                        "accountEnabled": u.account_enabled,
                        "department": u.department,
                        "jobTitle": u.job_title,
                    })
            return users
        except Exception as e:
            logger.error(f"search_users failed: {e}")
            raise

    # ── GET USER DETAILS ─────────────────────────────────────────────

    async def get_user_details(
        self,
        user_id: str,
        include_mfa: bool = True,
        include_sign_in: bool = True,
        include_groups: bool = False,
    ) -> dict:
        """Get comprehensive user details."""
        try:
            params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
                select=["id", "displayName", "userPrincipalName", "mail",
                        "accountEnabled", "department", "jobTitle",
                        "usageLocation", "assignedLicenses", "createdDateTime",
                        "signInActivity"],
            )
            config = RequestConfiguration(query_parameters=params)
            user = await self._client.users.by_user_id(user_id).get(
                request_configuration=config
            )

            result = {
                "id": user.id,
                "displayName": user.display_name,
                "userPrincipalName": user.user_principal_name,
                "mail": user.mail,
                "accountEnabled": user.account_enabled,
                "department": user.department,
                "jobTitle": user.job_title,
                "usageLocation": user.usage_location,
                "createdDateTime": str(user.created_date_time) if user.created_date_time else None,
                "assignedLicenses": [
                    {"skuId": lic.sku_id} for lic in (user.assigned_licenses or [])
                ],
            }

            # Sign-in activity
            if include_sign_in and user.sign_in_activity:
                result["lastSignIn"] = str(user.sign_in_activity.last_sign_in_date_time)
                result["lastNonInteractiveSignIn"] = str(
                    user.sign_in_activity.last_non_interactive_sign_in_date_time
                )

            # MFA methods
            if include_mfa:
                try:
                    methods = await self._client.users.by_user_id(user_id).authentication.methods.get()
                    result["authMethods"] = [
                        {"type": m.odata_type, "id": m.id}
                        for m in (methods.value or [])
                    ]
                except Exception:
                    result["authMethods"] = []

            # Groups
            if include_groups:
                try:
                    groups = await self._client.users.by_user_id(user_id).member_of.get()
                    result["groups"] = [
                        {"id": g.id, "displayName": getattr(g, "display_name", None)}
                        for g in (groups.value or [])
                    ]
                except Exception:
                    result["groups"] = []

            return result
        except Exception as e:
            logger.error(f"get_user_details failed for {user_id}: {e}")
            raise

    # ── CREATE USER ──────────────────────────────────────────────────

    async def create_user(
        self,
        display_name: str,
        mail_nickname: str,
        user_principal_name: str,
        password: str,
        force_change: bool = True,
        account_enabled: bool = True,
        department: str | None = None,
        job_title: str | None = None,
        usage_location: str | None = None,
    ) -> dict:
        """Create a new Entra ID user."""
        try:
            new_user = User(
                account_enabled=account_enabled,
                display_name=display_name,
                mail_nickname=mail_nickname,
                user_principal_name=user_principal_name,
                password_profile=PasswordProfile(
                    password=password,
                    force_change_password_next_sign_in=force_change,
                ),
                department=department,
                job_title=job_title,
                usage_location=usage_location,
            )

            created = await self._client.users.post(new_user)

            return {
                "id": created.id,
                "displayName": created.display_name,
                "userPrincipalName": created.user_principal_name,
                "accountEnabled": created.account_enabled,
                "createdDateTime": str(created.created_date_time),
            }
        except Exception as e:
            logger.error(f"create_user failed: {e}")
            raise

    # ── RESET PASSWORD ───────────────────────────────────────────────

    async def reset_password(
        self,
        user_id: str,
        new_password: str | None = None,
        force_change: bool = True,
    ) -> dict:
        """Reset a user's password."""
        if not new_password:
            new_password = self._generate_secure_password()

        try:
            user_update = User(
                password_profile=PasswordProfile(
                    password=new_password,
                    force_change_password_next_sign_in=force_change,
                )
            )
            await self._client.users.by_user_id(user_id).patch(user_update)

            return {
                "user_id": user_id,
                "password_reset": True,
                "temporary_password": new_password,
                "force_change_at_next_sign_in": force_change,
            }
        except Exception as e:
            logger.error(f"reset_password failed for {user_id}: {e}")
            raise

    # ── UPDATE USER ──────────────────────────────────────────────────

    async def update_user(self, user_id: str, updates: dict) -> dict:
        """Update user properties."""
        try:
            user_update = User()
            field_map = {
                "displayName": "display_name",
                "givenName": "given_name",
                "surname": "surname",
                "jobTitle": "job_title",
                "department": "department",
                "companyName": "company_name",
                "officeLocation": "office_location",
                "mobilePhone": "mobile_phone",
                "usageLocation": "usage_location",
                "accountEnabled": "account_enabled",
            }

            for graph_key, sdk_key in field_map.items():
                if graph_key in updates:
                    setattr(user_update, sdk_key, updates[graph_key])

            await self._client.users.by_user_id(user_id).patch(user_update)

            return {"user_id": user_id, "updated_fields": list(updates.keys()), "success": True}
        except Exception as e:
            logger.error(f"update_user failed for {user_id}: {e}")
            raise

    # ── DELETE USER ──────────────────────────────────────────────────

    async def delete_user(self, user_id: str) -> dict:
        """Soft-delete a user."""
        try:
            await self._client.users.by_user_id(user_id).delete()
            return {"user_id": user_id, "deleted": True, "recoverable_until": str(
                datetime.now(timezone.utc) + timedelta(days=30)
            )}
        except Exception as e:
            logger.error(f"delete_user failed for {user_id}: {e}")
            raise

    # ── LICENSE MANAGEMENT ───────────────────────────────────────────

    async def list_licenses(self, include_disabled: bool = False) -> list[dict]:
        """List all license SKUs in the tenant."""
        try:
            result = await self._client.subscribed_skus.get()
            licenses = []
            for sku in (result.value or []):
                total = sku.prepaid_units.enabled if sku.prepaid_units else 0
                consumed = sku.consumed_units or 0
                if not include_disabled and (total - consumed) <= 0:
                    continue
                licenses.append({
                    "skuId": sku.sku_id,
                    "skuPartNumber": sku.sku_part_number,
                    "totalUnits": total,
                    "consumedUnits": consumed,
                    "availableUnits": total - consumed,
                })
            return licenses
        except Exception as e:
            logger.error(f"list_licenses failed: {e}")
            raise

    async def assign_license(
        self, user_id: str, sku_id: str, disabled_plans: list[str] | None = None
    ) -> dict:
        """Assign a license to a user."""
        try:
            body = AssignLicensePostRequestBody(
                add_licenses=[
                    AssignedLicense(
                        sku_id=sku_id,
                        disabled_plans=disabled_plans or [],
                    )
                ],
                remove_licenses=[],
            )
            await self._client.users.by_user_id(user_id).assign_license.post(body)
            return {"user_id": user_id, "sku_id": sku_id, "assigned": True}
        except Exception as e:
            logger.error(f"assign_license failed for {user_id}: {e}")
            raise

    async def remove_license(self, user_id: str, sku_id: str) -> dict:
        """Remove a license from a user."""
        try:
            body = AssignLicensePostRequestBody(
                add_licenses=[],
                remove_licenses=[sku_id],
            )
            await self._client.users.by_user_id(user_id).assign_license.post(body)
            return {"user_id": user_id, "sku_id": sku_id, "removed": True}
        except Exception as e:
            logger.error(f"remove_license failed for {user_id}: {e}")
            raise

    # ── INSIGHTS REPORT DATA GATHERING ───────────────────────────────

    async def get_risky_sign_ins(self, lookback_days: int = 7) -> list[dict]:
        """Fetch risky sign-in events."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        try:
            from msgraph.generated.identity_protection.risky_users.risky_users_request_builder import RiskyUsersRequestBuilder
            params = RiskyUsersRequestBuilder.RiskyUsersRequestBuilderGetQueryParameters(
                filter=f"riskLastUpdatedDateTime ge {cutoff}",
                top=50,
            )
            config = RequestConfiguration(query_parameters=params)
            result = await self._client.identity_protection.risky_users.get(
                request_configuration=config
            )
            return [
                {
                    "id": u.id,
                    "userDisplayName": u.user_display_name,
                    "userPrincipalName": u.user_principal_name,
                    "riskLevel": str(u.risk_level) if u.risk_level else "unknown",
                    "riskState": str(u.risk_state) if u.risk_state else "unknown",
                }
                for u in (result.value or [])
            ]
        except Exception as e:
            logger.warning(f"get_risky_sign_ins failed (may need P1/P2 license): {e}")
            return []

    async def get_users_without_mfa(self) -> list[dict]:
        """Find users without registered MFA methods."""
        try:
            params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                select=["id", "displayName", "userPrincipalName"],
                top=999,
            )
            config = RequestConfiguration(query_parameters=params)
            users = await self._client.users.get(request_configuration=config)

            no_mfa = []
            for user in (users.value or []):
                try:
                    methods = await self._client.users.by_user_id(user.id).authentication.methods.get()
                    # Only password method = no MFA
                    method_types = [m.odata_type for m in (methods.value or [])]
                    has_strong = any(
                        t for t in method_types
                        if "password" not in t.lower()
                    )
                    if not has_strong:
                        no_mfa.append({
                            "id": user.id,
                            "displayName": user.display_name,
                            "userPrincipalName": user.user_principal_name,
                        })
                except Exception:
                    continue

            return no_mfa
        except Exception as e:
            logger.error(f"get_users_without_mfa failed: {e}")
            return []

    async def get_dormant_accounts(self, threshold_days: int = 90) -> list[dict]:
        """Find accounts with no sign-in activity for threshold_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
        try:
            params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                select=["id", "displayName", "userPrincipalName", "accountEnabled", "signInActivity"],
                top=999,
            )
            config = RequestConfiguration(query_parameters=params)
            result = await self._client.users.get(request_configuration=config)

            dormant = []
            for u in (result.value or []):
                if not u.sign_in_activity or not u.sign_in_activity.last_sign_in_date_time:
                    dormant.append({
                        "id": u.id,
                        "displayName": u.display_name,
                        "userPrincipalName": u.user_principal_name,
                        "lastSignIn": None,
                        "daysSinceSignIn": "Never",
                    })
                elif u.sign_in_activity.last_sign_in_date_time < cutoff:
                    days = (datetime.now(timezone.utc) - u.sign_in_activity.last_sign_in_date_time).days
                    dormant.append({
                        "id": u.id,
                        "displayName": u.display_name,
                        "userPrincipalName": u.user_principal_name,
                        "lastSignIn": str(u.sign_in_activity.last_sign_in_date_time),
                        "daysSinceSignIn": days,
                    })
            return dormant
        except Exception as e:
            logger.error(f"get_dormant_accounts failed: {e}")
            return []

    async def get_privileged_role_holders(self) -> list[dict]:
        """Get users with permanent privileged directory role assignments."""
        try:
            from msgraph.generated.role_management.directory.role_assignments.role_assignments_request_builder import RoleAssignmentsRequestBuilder
            params = RoleAssignmentsRequestBuilder.RoleAssignmentsRequestBuilderGetQueryParameters(
                expand=["principal", "roleDefinition"],
            )
            config = RequestConfiguration(query_parameters=params)
            assignments = await self._client.role_management.directory.role_assignments.get(
                request_configuration=config
            )
            holders = []
            for a in (assignments.value or []):
                role_name = a.role_definition.display_name if a.role_definition else "Unknown"
                principal_name = getattr(a.principal, "display_name", "Unknown") if a.principal else "Unknown"
                holders.append({
                    "principalId": a.principal_id,
                    "principalDisplayName": principal_name,
                    "roleId": a.role_definition_id,
                    "roleName": role_name,
                })
            return holders
        except Exception as e:
            logger.error(f"get_privileged_role_holders failed: {e}")
            return []

    async def get_guest_users(self) -> list[dict]:
        """List all guest users in the tenant."""
        try:
            params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
                filter="userType eq 'Guest'",
                select=["id", "displayName", "mail", "createdDateTime", "signInActivity"],
                top=200,
                count=True,
            )
            config = RequestConfiguration(query_parameters=params)
            config.headers.add("ConsistencyLevel", "eventual")
            result = await self._client.users.get(request_configuration=config)
            return [
                {
                    "id": u.id,
                    "displayName": u.display_name,
                    "mail": u.mail,
                    "createdDateTime": str(u.created_date_time) if u.created_date_time else None,
                }
                for u in (result.value or [])
            ]
        except Exception as e:
            logger.error(f"get_guest_users failed: {e}")
            return []

    # ── REPORT DELIVERY ──────────────────────────────────────────────

    async def send_channel_message(self, team_id: str, channel_id: str, content: str) -> dict:
        """Post a message to a Teams channel."""
        try:
            from msgraph.generated.models.chat_message import ChatMessage
            from msgraph.generated.models.item_body import ItemBody
            from msgraph.generated.models.body_type import BodyType

            message = ChatMessage(
                body=ItemBody(
                    content_type=BodyType.Html,
                    content=content,
                ),
            )
            result = await self._client.teams.by_team_id(team_id).channels.by_channel_id(channel_id).messages.post(
                message)
            return {"message_id": result.id, "sent": True}
        except Exception as e:
            logger.error(f"send_channel_message failed: {e}")
            raise

    async def send_mail(self, sender_upn: str, recipients: list[str], subject: str, html_body: str) -> dict:
        """Send an email via Microsoft Graph sendMail."""
        try:
            from msgraph.generated.users.item.send_mail.send_mail_post_request_body import SendMailPostRequestBody
            from msgraph.generated.models.message import Message
            from msgraph.generated.models.item_body import ItemBody
            from msgraph.generated.models.body_type import BodyType
            from msgraph.generated.models.recipient import Recipient
            from msgraph.generated.models.email_address import EmailAddress

            mail_body = SendMailPostRequestBody(
                message=Message(
                    subject=subject,
                    body=ItemBody(
                        content_type=BodyType.Html,
                        content=html_body,
                    ),
                    to_recipients=[
                        Recipient(email_address=EmailAddress(address=addr))
                        for addr in recipients
                    ],
                ),
                save_to_sent_items=False,
            )
            await self._client.users.by_user_id(sender_upn).send_mail.post(mail_body)
            return {"sent": True, "recipients": recipients}
        except Exception as e:
            logger.error(f"send_mail failed: {e}")
            raise

    # ── HELPERS ───────────────────────────────────────────────────────

    @staticmethod
    def _generate_secure_password(length: int = 16) -> str:
        """Generate a secure temporary password meeting Microsoft complexity requirements."""
        lower = secrets.choice(string.ascii_lowercase)
        upper = secrets.choice(string.ascii_uppercase)
        digit = secrets.choice(string.digits)
        special = secrets.choice("!@#$%^&*")
        remaining = "".join(
            secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*")
            for _ in range(length - 4)
        )
        password = list(lower + upper + digit + special + remaining)
        secrets.SystemRandom().shuffle(password)
        return "".join(password)
