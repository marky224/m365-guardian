# M365 Guardian — Sample Conversation Flows

## Scenario 1: Create a User + Exchange Online Mailbox

```
┌─────────────────────────────────────────────────────────────────────┐
│  SCENARIO 1: User + Mailbox Creation                                │
└─────────────────────────────────────────────────────────────────────┘

👤 Technician:
   Create a new user named Sarah Chen in the Engineering department.
   Her email should be sarah.chen@contoso.com. She needs a Microsoft
   365 Business Basic license and an Exchange mailbox.

🛡️ M365 Guardian:
   I'll set up Sarah Chen for you. Let me first check available
   licenses.

   [🔧 Tool call: list_available_licenses]

   ✅ Microsoft 365 Business Basic has 12 available licenses.

   Here's what I'll do:

   ┌─────────────────────────────────────────┐
   │  M365 GUARDIAN — ACTION SUMMARY         │
   ├─────────────────────────────────────────┤
   │  Action:    Create new user + mailbox   │
   │  Target:    sarah.chen@contoso.com      │
   │  Changes:                               │
   │   • Display name: Sarah Chen            │
   │   • UPN: sarah.chen@contoso.com         │
   │   • Department: Engineering             │
   │   • Usage location: US                  │
   │   • License: Microsoft 365 Business     │
   │     Basic (includes Exchange Online)    │
   │   • Temporary password: ********        │
   │   • Force password change: Yes          │
   │   • Mailbox: Auto-provisioned with      │
   │     license                             │
   │  Warnings:                              │
   │   • User will be prompted to change     │
   │     password on first sign-in           │
   │   • Mailbox may take up to 15 minutes   │
   │     to provision after license          │
   │     assignment                          │
   │  Audit ID:  a1b2c3d4-e5f6-7890-...     │
   └─────────────────────────────────────────┘
   ⚠️  Type YES to proceed, or anything else to cancel.

👤 Technician:
   YES

🛡️ M365 Guardian:
   [🔧 Tool call: create_user]
   [🔧 Tool call: assign_license]

   ✅ **User created successfully!**

   | Field              | Value                        |
   |--------------------|------------------------------|
   | Display Name       | Sarah Chen                   |
   | UPN                | sarah.chen@contoso.com       |
   | Object ID          | 8f4e2a1b-...                 |
   | Department         | Engineering                  |
   | License            | Microsoft 365 Business Basic |
   | Temp Password      | Tr@ns!t_8xK2mP              |
   | Must Change Pass   | Yes                          |
   | Account Enabled    | Yes                          |

   📬 The Exchange Online mailbox will be provisioned automatically
   within a few minutes. You can check its status by asking me:
   "Check mailbox status for sarah.chen@contoso.com"

   **Next steps:**
   - Share the temporary password with Sarah securely
   - Ask her to sign in and set up MFA
   - Want me to enforce MFA for Sarah now?

👤 Technician:
   Yes, enforce MFA for her.

🛡️ M365 Guardian:
   ┌─────────────────────────────────────────┐
   │  M365 GUARDIAN — ACTION SUMMARY         │
   ├─────────────────────────────────────────┤
   │  Action:    Enforce MFA                 │
   │  Target:    sarah.chen@contoso.com      │
   │  Changes:                               │
   │   • MFA state → Enforced               │
   │   • User will be required to register   │
   │     an MFA method at next sign-in       │
   │  Warnings:  None                        │
   │  Audit ID:  b2c3d4e5-f6a7-8901-...     │
   └─────────────────────────────────────────┘
   ⚠️  Type YES to proceed, or anything else to cancel.

👤 Technician:
   YES

🛡️ M365 Guardian:
   [🔧 Tool call: enforce_mfa]

   ✅ **MFA enforced for Sarah Chen.**

   Sarah will be required to register a multifactor authentication
   method the next time she signs in. She can use the Microsoft
   Authenticator app, a phone number, or a security key.

   📋 Audit trail updated — all actions logged under session
   a1b2c3d4.
```

---

## Scenario 2: Password Reset + MFA Enforcement

```
┌─────────────────────────────────────────────────────────────────────┐
│  SCENARIO 2: Password Reset + MFA Enforcement                       │
└─────────────────────────────────────────────────────────────────────┘

👤 Technician:
   John Martinez locked himself out. Can you reset his password?

🛡️ M365 Guardian:
   Let me find John Martinez first.

   [🔧 Tool call: search_users(query="John Martinez")]

   I found 1 match:

   | Name            | Email                      | Status  |
   |-----------------|----------------------------|---------|
   | John Martinez   | john.martinez@contoso.com  | Enabled |

   Is this the correct user?

👤 Technician:
   Yes, that's him.

🛡️ M365 Guardian:
   [🔧 Tool call: get_user_details(user_id="john.martinez@contoso.com")]

   Here are John's details:
   - **Account:** Enabled
   - **Department:** Sales
   - **Last sign-in:** 2 hours ago (failed — likely lockout)
   - **MFA methods:** ⚠️ None registered
   - **Licenses:** Microsoft 365 Business Premium

   ⚠️ **Security alert:** John has no MFA methods registered.
   I strongly recommend enforcing MFA along with the password reset.

   I'll generate a secure temporary password. Here's the plan:

   ┌─────────────────────────────────────────┐
   │  M365 GUARDIAN — ACTION SUMMARY         │
   ├─────────────────────────────────────────┤
   │  Action:    Reset password              │
   │  Target:    john.martinez@contoso.com   │
   │  Changes:                               │
   │   • New temporary password generated    │
   │   • Force change at next sign-in: Yes   │
   │  Warnings:                              │
   │   • No MFA registered — recommend       │
   │     enforcing MFA after reset           │
   │  Audit ID:  c3d4e5f6-a7b8-9012-...     │
   └─────────────────────────────────────────┘
   ⚠️  Type YES to proceed, or anything else to cancel.

👤 Technician:
   YES

🛡️ M365 Guardian:
   [🔧 Tool call: reset_password(user_id="john.martinez@contoso.com")]

   ✅ **Password reset successful!**

   | Field              | Value                         |
   |--------------------|-------------------------------|
   | User               | John Martinez                 |
   | Temp Password      | Kx#9mR!pL2wQ7n               |
   | Must Change Pass   | Yes                           |

   🔒 **Shall I also enforce MFA for John?** Given he has no MFA
   methods registered, this is a high-priority security recommendation.

👤 Technician:
   Yes, enforce MFA.

🛡️ M365 Guardian:
   ┌─────────────────────────────────────────┐
   │  M365 GUARDIAN — ACTION SUMMARY         │
   ├─────────────────────────────────────────┤
   │  Action:    Enforce MFA                 │
   │  Target:    john.martinez@contoso.com   │
   │  Changes:                               │
   │   • MFA state → Enforced               │
   │  Warnings:  None                        │
   │  Audit ID:  d4e5f6a7-b8c9-0123-...     │
   └─────────────────────────────────────────┘
   ⚠️  Type YES to proceed, or anything else to cancel.

👤 Technician:
   YES

🛡️ M365 Guardian:
   [🔧 Tool call: enforce_mfa(user_id="john.martinez@contoso.com")]

   ✅ **MFA enforced for John Martinez.**

   **Summary of actions taken:**
   1. ✅ Password reset — temporary password generated
   2. ✅ MFA enforced — John will register an MFA method at next sign-in

   Please share the temporary password with John through a secure
   channel (not email). He'll need to:
   1. Sign in with the temporary password
   2. Set a new password
   3. Register an MFA method (Authenticator app recommended)
```

---

## Scenario 3: Weekly Security Insights Report

```
┌─────────────────────────────────────────────────────────────────────┐
│  SCENARIO 3: Automated Weekly Security Report                       │
└─────────────────────────────────────────────────────────────────────┘

👤 Technician:
   Generate the weekly security report.

🛡️ M365 Guardian:
   Running all 10 security checks now... This may take a moment.

   [🔧 Tool call: generate_weekly_insights_report]

   ---

   # 🛡️ M365 Guardian — Weekly Security Insights
   **Generated:** 2026-04-13T08:00:00Z | **Lookback:** 7 days

   ## Executive Summary
   M365 Guardian found **14 findings** across 10 checks. 2 critical,
   3 warnings. Overall tenant health: 🔴 Critical.

   ---

   ### 🔴 1. Suspicious Sign-Ins
   **4 risky sign-ins detected — immediate review recommended.**
   | User | Risk Level | State |
   |------|------------|-------|
   | alex.wong@contoso.com | High | atRisk |
   | maria.garcia@contoso.com | Medium | atRisk |
   | temp.contractor@contoso.com | High | atRisk |
   | john.martinez@contoso.com | Low | remediated |
   → [Fix: Review risky users]

   ### 🔴 2. MFA Compliance Gaps
   **6 users without MFA — significant security risk.**
   | User | Department |
   |------|------------|
   | temp.contractor@contoso.com | Contractors |
   | summer.intern1@contoso.com | Interns |
   | summer.intern2@contoso.com | Interns |
   | kiosk.account@contoso.com | Operations |
   | john.martinez@contoso.com | Sales |
   → [Fix: Enforce MFA for these users]

   ### 🟡 3. Dormant / Inactive Accounts
   **3 accounts inactive for 90+ days.**
   | User | Last Sign-In | Days Inactive |
   |------|-------------|---------------|
   | former.employee@contoso.com | 2025-12-01 | 133 |
   | old.service@contoso.com | Never | Never |
   | test.account@contoso.com | 2025-11-15 | 149 |
   → [Fix: Disable account former.employee@contoso.com]

   ### 🟢 4. License Optimization
   **License utilization is healthy.** No significant waste detected.

   ### 🟡 5. Privileged Access Hygiene
   **4 permanent privileged admins — consider reducing or using PIM.**
   | Admin | Role |
   |-------|------|
   | admin@contoso.com | Global Administrator |
   | it.lead@contoso.com | Global Administrator |
   | helpdesk@contoso.com | Exchange Administrator |
   | devops@contoso.com | Global Administrator |
   → [Fix: Review admin roles — Microsoft recommends max 2 Global Admins]

   ### 🟡 6. Guest User & External Access
   **12 guest users in the tenant.** Within normal range.

   ### 🟡 7. Legacy Authentication Usage
   **Ensure Conditional Access blocks legacy auth protocols.**
   → [Fix: Create CA policy to block legacy auth]

   ### 🟢 8. Exchange Online Best Practices
   No issues detected.

   ### 🟡 9. Conditional Access & Risk Policy Gaps
   **Recommendations:**
   - Require MFA for all users (not just admins)
   - Block legacy authentication protocols
   - Require compliant devices for admin access

   ### 🟢 10. Password & Authentication Hygiene
   SSPR and banned password lists are enabled.

   ---

   **Top priorities this week:**
   1. 🔴 Investigate 4 risky sign-ins (especially the 2 high-risk ones)
   2. 🔴 Enforce MFA for the 6 users without it
   3. 🟡 Disable or delete 3 dormant accounts
   4. 🟡 Reduce permanent Global Admin count from 3 to 2

   Would you like me to:
   - Send this report to Teams and email?
   - Start fixing any of these issues?

👤 Technician:
   Send it to Teams and email. Then let's bulk-enforce MFA for those
   6 users.

🛡️ M365 Guardian:
   [🔧 Tool call: send_report_to_teams]
   [🔧 Tool call: send_report_via_email]

   ✅ Report delivered:
   - Teams channel: ✅ Posted
   - Email: ✅ Sent to admin@contoso.com, it-lead@contoso.com

   Now for the bulk MFA enforcement:

   ┌─────────────────────────────────────────┐
   │  M365 GUARDIAN — ACTION SUMMARY         │
   ├─────────────────────────────────────────┤
   │  Action:    Bulk enforce MFA            │
   │  Target:    6 users                     │
   │  Users:                                 │
   │   1. temp.contractor@contoso.com        │
   │   2. summer.intern1@contoso.com         │
   │   3. summer.intern2@contoso.com         │
   │   4. kiosk.account@contoso.com          │
   │   5. john.martinez@contoso.com          │
   │   6. new.hire@contoso.com               │
   │  Changes:                               │
   │   • MFA state → Enforced for all       │
   │   • All users must register MFA at      │
   │     next sign-in                        │
   │  Warnings:                              │
   │   • kiosk.account may need a            │
   │     specialized MFA method (FIDO2 key)  │
   │  Audit ID:  e5f6a7b8-c9d0-1234-...     │
   └─────────────────────────────────────────┘
   ⚠️  Type YES to proceed, or anything else to cancel.

👤 Technician:
   YES

🛡️ M365 Guardian:
   [🔧 Tool call: bulk_operation(operation="enforce_mfa", user_ids=[...])]

   ✅ **Bulk MFA enforcement complete!**

   | User | Status |
   |------|--------|
   | temp.contractor@contoso.com | ✅ MFA enforced |
   | summer.intern1@contoso.com | ✅ MFA enforced |
   | summer.intern2@contoso.com | ✅ MFA enforced |
   | kiosk.account@contoso.com | ✅ MFA enforced |
   | john.martinez@contoso.com | ✅ MFA enforced |
   | new.hire@contoso.com | ✅ MFA enforced |

   All 6 users will be prompted to register an MFA method at their
   next sign-in. For kiosk.account, consider setting up a FIDO2
   security key since it's a shared device.

   📋 All actions logged — 8 audit entries created for this session.

   Shall I tackle the dormant accounts next?
```

---

## Additional Quick Examples

### Search for a User
```
👤 "Find the user alex wong"
🛡️ [searches, returns results in table format]
```

### Check Mailbox Status
```
👤 "Check if sarah.chen has her mailbox set up yet"
🛡️ [checks mailbox provisioning status, shows storage and permissions]
```

### View Audit Trail
```
👤 "Show me all actions from today"
🛡️ [queries audit log, displays chronological list with user, action, and status]
```

### Disable an Account
```
👤 "Disable the account for former.employee@contoso.com"
🛡️ [shows confirmation with warning about mailbox access, asks for YES]
```

### Assign a License
```
👤 "Give sarah.chen a Microsoft 365 Business Premium license"
🛡️ [checks availability, shows confirmation, assigns on YES]
```
