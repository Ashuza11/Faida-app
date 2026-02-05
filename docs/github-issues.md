# Faida App - GitHub Issues

## 🏗️ Infrastructure & DevOps

### Issue #1: Migrate Database from SQLite/PostgreSQL to Neon DB

**Labels:** `infrastructure`, `database`, `priority-high`

**Description:**
Migrate the application database from local SQLite/PostgreSQL to Neon serverless PostgreSQL for production deployment.

**Tasks:**

- [ ] Create Neon DB account and project
- [ ] Update `config.py` with Neon connection string
- [ ] Configure connection pooling (Neon uses PgBouncer)
- [ ] Update SQLAlchemy settings for serverless compatibility
- [ ] Test migrations with Neon
- [ ] Update environment variables for production

**Acceptance Criteria:**

- Application connects to Neon DB successfully
- All migrations run without errors
- Connection pooling is properly configured

---

### Issue #2: Set Up CI/CD Pipeline with GitHub Actions and Render

**Labels:** `infrastructure`, `devops`, `priority-high`

**Description:**
Implement automated deployment pipeline that deploys to Render when changes are merged from `develop` to `main`.

**Tasks:**

- [ ] Create `.github/workflows/deploy.yml`
- [ ] Configure Render deploy hook
- [ ] Set up environment secrets in GitHub
- [ ] Configure branch protection rules
- [ ] Add automated testing before deployment
- [ ] Document deployment process

**Acceptance Criteria:**

- Merging to `main` triggers automatic deployment
- Failed tests prevent deployment
- Deployment status is visible in GitHub

---

### Issue #3: Refactor Docker Configuration for Production

**Labels:** `infrastructure`, `docker`, `priority-medium`

**Description:**
Evaluate and improve the Docker setup for production deployment on Render.

**Tasks:**

- [ ] Review and optimize `Dockerfile`
- [ ] Update `docker-compose.yml` for local development
- [ ] Create production-specific Docker configuration
- [ ] Optimize image size
- [ ] Update entrypoint scripts

**Acceptance Criteria:**

- Docker builds successfully
- Production image is optimized
- Local development workflow is documented

---

## 🎨 Design & UI/UX

### Issue #4: Update Brand Colors and Logo

**Labels:** `design`, `ui`, `priority-high`

**Description:**
Update the application design to match the new brand colors:

- Logo icon: `#F58320` (Orange)
- Logo text: `#5E72E4` (Blue/Purple)

**Tasks:**

- [ ] Update SCSS variables with new colors
- [ ] Replace logo assets
- [ ] Update navbar styling
- [ ] Update button primary/secondary colors
- [ ] Update sidebar active states
- [ ] Ensure consistent color usage across all pages

**Files to modify:**

- `src/apps/static/assets/scss/custom/_variables.scss`
- `src/apps/static/assets/img/brand/`
- `src/apps/templates/includes/navigation.html`
- `src/apps/templates/includes/sidenav.html`

**Acceptance Criteria:**

- All brand elements use new colors
- Design is consistent across all pages
- Colors pass accessibility contrast checks

---

### Issue #5: Redesign Login and Registration Pages

**Labels:** `design`, `ui`, `auth`, `priority-high`

**Description:**
Modernize the login and registration pages with improved UX and the new brand identity.

**Tasks:**

- [ ] Design new login page layout
- [ ] Design new registration page layout
- [ ] Add phone number field styling
- [ ] Implement form validation feedback
- [ ] Add loading states
- [ ] Make responsive for mobile

**Files to modify:**

- `src/apps/templates/auth/login.html`
- `src/apps/templates/auth/register.html`
- `src/apps/static/assets/scss/`

**Acceptance Criteria:**

- Modern, clean design
- Mobile responsive
- Clear validation feedback
- Matches new brand colors

---

### Issue #6: Fix Mobile Responsive Issues

**Labels:** `design`, `ui`, `mobile`, `priority-medium`

**Description:**
Fix mobile display issues, particularly with button positioning in sale edit views.

**Tasks:**

- [ ] Fix "modifier vente" and "retour aux ventes" button positioning on mobile
- [ ] Shorten button text for small screens
- [ ] Review all pages for mobile responsiveness
- [ ] Add CSS media queries where needed

**Files to modify:**

- `src/apps/templates/main/edit_sale.html`
- `src/apps/templates/main/vente_stock.html`
- `src/apps/static/assets/scss/`

**Acceptance Criteria:**

- Buttons display correctly on mobile
- Text is readable on all screen sizes
- No horizontal scrolling on mobile

---

### Issue #7: Add Loading Indicators

**Labels:** `design`, `ux`, `priority-medium`

**Description:**
Add loading spinners/indicators for processes that take time.

**Tasks:**

- [ ] Create reusable loading component
- [ ] Add loader for data registration
- [ ] Add loader for data fetching/display
- [ ] Add loader for form submissions
- [ ] Add skeleton loaders for tables

**Acceptance Criteria:**

- Users see feedback during loading
- Loaders appear for operations > 200ms
- Consistent loader design across app

---

## 🔐 Authentication & User Management

### Issue #8: Convert Authentication from Email to Phone Number

**Labels:** `auth`, `backend`, `priority-high`

**Description:**
Adapt the authentication system for local context (Bukavu, Goma, Lubumbashi) by using phone numbers instead of email for login.

**Tasks:**

- [ ] Update User model - phone number required, email optional
- [ ] Update registration form
- [ ] Update login form to use phone number
- [ ] Update authentication logic
- [ ] Add phone number validation (DRC format)
- [ ] Update password reset flow
- [ ] Migrate existing user data

**Files to modify:**

- `src/apps/models.py`
- `src/apps/auth/forms.py`
- `src/apps/auth/routes.py`
- `src/apps/auth/utils.py`
- `src/apps/templates/auth/login.html`
- `src/apps/templates/auth/register.html`

**Acceptance Criteria:**

- Users can register with phone number
- Users can login with phone number + password
- Email is optional (super admin only)
- Phone validation works for DRC numbers

---

### Issue #9: Update Profile Page - Phone Required, Email Optional

**Labels:** `auth`, `profile`, `priority-medium`

**Description:**
Update the profile page to make phone number mandatory and email optional.

**Tasks:**

- [ ] Update profile form validation
- [ ] Update profile template
- [ ] Add phone number edit capability
- [ ] Update user settings

**Files to modify:**

- `src/apps/templates/main/profile.html`
- `src/apps/main/forms.py`
- `src/apps/main/routes.py`

**Acceptance Criteria:**

- Phone number is required in profile
- Email is optional
- Users can update their phone number

---

## 🐛 Bug Fixes

### Issue #10: Fix Toast Notification System

**Labels:** `bug`, `notifications`, `priority-high`

**Description:**
Correct all incorrect toast notifications throughout the application.

**Tasks:**

- [ ] Audit all flash messages/toasts
- [ ] Fix incorrect notification messages
- [ ] Standardize notification types (success, error, warning, info)
- [ ] Ensure notifications appear at correct times
- [ ] Fix notification dismissal

**Files to modify:**

- `src/apps/templates/includes/_messages.html`
- All route files with flash messages

**Acceptance Criteria:**

- All notifications show correct messages
- Notifications are properly categorized
- Notifications can be dismissed

---

### Issue #11: Fix Geolocation Feature

**Labels:** `bug`, `geolocation`, `priority-medium`

**Description:**
The get location feature is not working consistently.

**Tasks:**

- [ ] Debug geolocation API calls
- [ ] Add error handling for denied permissions
- [ ] Add fallback for unsupported browsers
- [ ] Improve accuracy settings
- [ ] Add loading state during location fetch
- [ ] Store location data properly

**Files to modify:**

- `src/apps/templates/main/client_map.html`
- `src/apps/main/routes.py`
- JavaScript files handling geolocation

**Acceptance Criteria:**

- Location fetching works reliably
- Users see clear error messages when it fails
- Fallback options available

---

### Issue #12: Fix Terrain (Map) Tab Active State

**Labels:** `bug`, `ui`, `priority-low`

**Description:**
The Terrain tab doesn't show as active when opened.

**Tasks:**

- [ ] Fix active state CSS for Terrain tab
- [ ] Use real client location data on map
- [ ] Display purchasing volumes on map
- [ ] Add time filtering (week/month)

**Files to modify:**

- `src/apps/templates/main/client_map.html`
- `src/apps/templates/includes/sidenav.html`
- `src/apps/main/routes.py`

**Acceptance Criteria:**

- Tab shows as active when selected
- Map displays real client positions
- Purchase volumes are visualized

---

### Issue #13: Fix Rapport Tab Active State and Add Archive Mode

**Labels:** `bug`, `feature`, `priority-medium`

**Description:**
Fix the Rapport tab active state and add report archiving functionality.

**Tasks:**

- [ ] Fix active state for Rapport tab
- [ ] Design archive confirmation modal
- [ ] Implement archive functionality
- [ ] Add archived reports view

**Files to modify:**

- `src/apps/templates/main/rapports.html`
- `src/apps/templates/includes/sidenav.html`
- `src/apps/main/routes.py`

**Acceptance Criteria:**

- Tab shows as active when selected
- Users can archive reports with confirmation
- Archived reports are accessible

---

### Issue #14: Fix Client Tab Active State in Admin

**Labels:** `bug`, `ui`, `priority-low`

**Description:**
The Client tab doesn't show as active when on the clients page.

**Tasks:**

- [ ] Fix active state detection for Client tab
- [ ] Update sidenav logic

**Files to modify:**

- `src/apps/templates/includes/sidenav.html`
- `src/apps/templates/main/clients.html`

**Acceptance Criteria:**

- Client tab shows as active when selected

---

## ✨ Features & Improvements

### Issue #15: Update "Ajouter Stockeur" Modal

**Labels:** `feature`, `ui`, `priority-medium`

**Description:**
Update the add stocker modal to remove unnecessary fields.

**Tasks:**

- [ ] Remove vendor/client dropdown (only stockers)
- [ ] Replace email with phone number
- [ ] Make email optional
- [ ] Update form validation

**Files to modify:**

- `src/apps/templates/includes/modal_form.html`
- `src/apps/main/forms.py`
- `src/apps/main/routes.py`

**Acceptance Criteria:**

- Modal shows only relevant fields
- Phone number is primary contact
- Email is optional

---

### Issue #16: Add WhatsApp Support Link

**Labels:** `feature`, `support`, `priority-low`

**Description:**
Add a WhatsApp link for customer support.

**Tasks:**

- [ ] Add WhatsApp icon to support section
- [ ] Configure WhatsApp link with pre-filled message
- [ ] Add to sidebar or footer

**Files to modify:**

- `src/apps/templates/includes/sidenav.html`
- `src/apps/templates/includes/footer.html`

**Acceptance Criteria:**

- WhatsApp link opens WhatsApp with support number
- Pre-filled message for context

---

## 🧹 Code Quality

### Issue #17: Standardize Naming Conventions

**Labels:** `refactor`, `code-quality`, `priority-medium`

**Description:**
Standardize all route names, function names, and file names. Choose either French or English (recommend English for code).

**Tasks:**

- [ ] Audit all route names
- [ ] Audit all function names
- [ ] Create naming convention document
- [ ] Rename routes consistently
- [ ] Rename functions consistently
- [ ] Update all references
- [ ] Update templates

**Files to modify:**

- `src/apps/main/routes.py`
- `src/apps/auth/routes.py`
- All template files

**Naming Convention to Follow:**

```
Routes: /clients, /sales, /stock-purchases, /reports
Functions: get_clients(), create_sale(), update_stock()
Templates: clients.html, sales.html, edit_sale.html
```

**Acceptance Criteria:**

- Consistent English naming throughout
- No mixed French/English
- All references updated

---

### Issue #18: Clean Up and Organize Code

**Labels:** `refactor`, `code-quality`, `priority-medium`

**Description:**
General code cleanup and organization.

**Tasks:**

- [ ] Remove unused imports
- [ ] Remove dead code
- [ ] Add proper docstrings
- [ ] Organize imports (standard, third-party, local)
- [ ] Add type hints where appropriate
- [ ] Fix linting errors

**Acceptance Criteria:**

- Code passes linting
- All files properly documented
- No unused code

---

### Issue #19: Improve Flask CLI Commands for Production

**Labels:** `infrastructure`, `cli`, `priority-medium`

**Description:**
Evaluate and improve the initialization CLI commands for production.

**Current commands:**

```bash
flask setup create-superadmin
flask setup init-stock
flask setup seed-reports --date 2025-11-11
flask db init
flask db migrate -m "Initial migration."
flask db upgrade
```

**Tasks:**

- [ ] Create single initialization command
- [ ] Add idempotent checks (don't duplicate data)
- [ ] Add production safety checks
- [ ] Document all CLI commands
- [ ] Add rollback capabilities

**Files to modify:**

- `src/apps/cli.py`
- `README.md`

**Acceptance Criteria:**

- Single command for full setup
- Safe to run multiple times
- Clear documentation

---

## 📋 Issue Summary by Priority

### High Priority

1. #1 - Migrate to Neon DB
2. #2 - Set Up CI/CD
3. #4 - Update Brand Colors
4. #5 - Redesign Login/Register
5. #8 - Phone Number Authentication
6. #10 - Fix Toast Notifications

### Medium Priority

7. #3 - Refactor Docker Config
8. #6 - Fix Mobile Responsive
9. #7 - Add Loading Indicators
10. #9 - Update Profile Page
11. #13 - Fix Rapport Tab + Archive
12. #15 - Update Stockeur Modal
13. #17 - Standardize Naming
14. #18 - Code Cleanup
15. #19 - Improve CLI Commands

### Low Priority

16. #11 - Fix Geolocation
17. #12 - Fix Terrain Tab
18. #14 - Fix Client Tab
19. #16 - Add WhatsApp Link
