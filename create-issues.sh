#!/bin/bash
# ===========================================
# Script to Create GitHub Issues for AirtFast Renovation
# ===========================================
# Prerequisites: GitHub CLI (gh) installed and authenticated
# Run: ./create-issues.sh

set -e

echo "🚀 Creating GitHub Issues for AirtFast Renovation..."
echo ""

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) is not installed."
    echo "Install it from: https://cli.github.com/"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ Not authenticated with GitHub CLI."
    echo "Run: gh auth login"
    exit 1
fi

echo "✅ GitHub CLI authenticated"
echo ""

# ===========================================
# Infrastructure Issues
# ===========================================

echo "🏷️  Ensuring all labels exist..."

declare -A LABELS=(
  ["infrastructure"]="1f6feb"
  ["database"]="0969da"
  ["devops"]="0e8a16"
  ["docker"]="2496ed"
  ["design"]="d4c5f9"
  ["ui"]="a2eeef"
  ["ux"]="bfdadc"
  ["mobile"]="c2e0c6"
  ["auth"]="f9d0c4"
  ["backend"]="5319e7"
  ["profile"]="fbca04"
  ["bug"]="d73a4a"
  ["notifications"]="e99695"
  ["geolocation"]="0052cc"
  ["feature"]="84b6eb"
  ["support"]="0e8a16"
  ["refactor"]="d876e3"
  ["code-quality"]="fef2c0"
  ["cli"]="ededed"
  ["priority-high"]="b60205"
  ["priority-medium"]="fbca04"
  ["priority-low"]="0e8a16"
)

# Get ALL labels (no pagination issue)
EXISTING_LABELS=$(gh label list --limit 1000 --json name -q '.[].name')

for LABEL in "${!LABELS[@]}"; do
  if ! echo "$EXISTING_LABELS" | grep -qx "$LABEL"; then
    echo "➕ Creating label: $LABEL"
    gh label create "$LABEL" --color "${LABELS[$LABEL]}"
  else
    echo "✅ Label exists: $LABEL"
  fi
done

echo "🎉 All labels verified"





echo "📦 Creating Infrastructure Issues..."

gh issue create \
  --title "[INFRA] Migrate Database from SQLite/PostgreSQL to Neon DB" \
  --body "## Description
Migrate the application database from local SQLite/PostgreSQL to Neon serverless PostgreSQL for production deployment.

## Tasks
- [ ] Create Neon DB account and project
- [ ] Update config.py with Neon connection string
- [ ] Configure connection pooling (Neon uses PgBouncer)
- [ ] Update SQLAlchemy settings for serverless compatibility
- [ ] Test migrations with Neon
- [ ] Update environment variables for production

## Acceptance Criteria
- Application connects to Neon DB successfully
- All migrations run without errors
- Connection pooling is properly configured" \
  --label "infrastructure,database,priority-high"

gh issue create \
  --title "[INFRA] Set Up CI/CD Pipeline with GitHub Actions and Render" \
  --body "## Description
Implement automated deployment pipeline that deploys to Render when changes are merged from develop to main.

## Tasks
- [ ] Create .github/workflows/deploy.yml
- [ ] Configure Render deploy hook
- [ ] Set up environment secrets in GitHub
- [ ] Configure branch protection rules
- [ ] Add automated testing before deployment
- [ ] Document deployment process

## Acceptance Criteria
- Merging to main triggers automatic deployment
- Failed tests prevent deployment
- Deployment status is visible in GitHub" \
  --label "infrastructure,devops,priority-high"

gh issue create \
  --title "[INFRA] Refactor Docker Configuration for Production" \
  --body "## Description
Evaluate and improve the Docker setup for production deployment on Render.

## Tasks
- [ ] Review and optimize Dockerfile
- [ ] Update docker-compose.yml for local development
- [ ] Create production-specific Docker configuration
- [ ] Optimize image size
- [ ] Update entrypoint scripts

## Acceptance Criteria
- Docker builds successfully
- Production image is optimized
- Local development workflow is documented" \
  --label "infrastructure,docker,priority-medium"

# ===========================================
# Design Issues
# ===========================================

echo "🎨 Creating Design Issues..."

gh issue create \
  --title "[DESIGN] Update Brand Colors and Logo" \
  --body "## Description
Update the application design to match the new brand colors:
- Logo icon: #F58320 (Orange)
- Logo text: #5E72E4 (Blue/Purple)

## Tasks
- [ ] Update SCSS variables with new colors
- [ ] Replace logo assets
- [ ] Update navbar styling
- [ ] Update button primary/secondary colors
- [ ] Update sidebar active states
- [ ] Ensure consistent color usage across all pages

## Files to modify
- src/apps/static/assets/scss/custom/_variables.scss
- src/apps/static/assets/img/brand/
- src/apps/templates/includes/navigation.html
- src/apps/templates/includes/sidenav.html

## Acceptance Criteria
- All brand elements use new colors
- Design is consistent across all pages
- Colors pass accessibility contrast checks" \
  --label "design,ui,priority-high"

gh issue create \
  --title "[DESIGN] Redesign Login and Registration Pages" \
  --body "## Description
Modernize the login and registration pages with improved UX and the new brand identity.

## Tasks
- [ ] Design new login page layout
- [ ] Design new registration page layout
- [ ] Add phone number field styling
- [ ] Implement form validation feedback
- [ ] Add loading states
- [ ] Make responsive for mobile

## Acceptance Criteria
- Modern, clean design
- Mobile responsive
- Clear validation feedback
- Matches new brand colors" \
  --label "design,ui,auth,priority-high"

gh issue create \
  --title "[DESIGN] Fix Mobile Responsive Issues" \
  --body "## Description
Fix mobile display issues, particularly with button positioning in sale edit views.

## Tasks
- [ ] Fix 'modifier vente' and 'retour aux ventes' button positioning on mobile
- [ ] Shorten button text for small screens
- [ ] Review all pages for mobile responsiveness
- [ ] Add CSS media queries where needed

## Acceptance Criteria
- Buttons display correctly on mobile
- Text is readable on all screen sizes
- No horizontal scrolling on mobile" \
  --label "design,ui,mobile,priority-medium"

gh issue create \
  --title "[DESIGN] Add Loading Indicators" \
  --body "## Description
Add loading spinners/indicators for processes that take time.

## Tasks
- [ ] Create reusable loading component
- [ ] Add loader for data registration
- [ ] Add loader for data fetching/display
- [ ] Add loader for form submissions
- [ ] Add skeleton loaders for tables

## Acceptance Criteria
- Users see feedback during loading
- Loaders appear for operations > 200ms
- Consistent loader design across app" \
  --label "design,ux,priority-medium"

# ===========================================
# Authentication Issues
# ===========================================

echo "🔐 Creating Authentication Issues..."

gh issue create \
  --title "[AUTH] Convert Authentication from Email to Phone Number" \
  --body "## Description
Adapt the authentication system for local context (Bukavu, Goma, Lubumbashi) by using phone numbers instead of email for login.

## Tasks
- [ ] Update User model - phone number required, email optional
- [ ] Update registration form
- [ ] Update login form to use phone number
- [ ] Update authentication logic
- [ ] Add phone number validation (DRC format)
- [ ] Update password reset flow
- [ ] Migrate existing user data

## DRC Phone Format
- Country code: +243
- Valid prefixes: 81, 82, 83, 84, 85 (Vodacom), 89, 99 (Airtel), 90, 91, 97, 98 (Orange), 80, 86, 87, 88 (Africell)

## Acceptance Criteria
- Users can register with phone number
- Users can login with phone number + password
- Email is optional (super admin only)
- Phone validation works for DRC numbers" \
  --label "auth,backend,priority-high"

gh issue create \
  --title "[AUTH] Update Profile Page - Phone Required, Email Optional" \
  --body "## Description
Update the profile page to make phone number mandatory and email optional.

## Tasks
- [ ] Update profile form validation
- [ ] Update profile template
- [ ] Add phone number edit capability
- [ ] Update user settings

## Acceptance Criteria
- Phone number is required in profile
- Email is optional
- Users can update their phone number" \
  --label "auth,profile,priority-medium"

# ===========================================
# Bug Fix Issues
# ===========================================

echo "🐛 Creating Bug Fix Issues..."

gh issue create \
  --title "[BUG] Fix Toast Notification System" \
  --body "## Description
Correct all incorrect toast notifications throughout the application.

## Tasks
- [ ] Audit all flash messages/toasts
- [ ] Fix incorrect notification messages
- [ ] Standardize notification types (success, error, warning, info)
- [ ] Ensure notifications appear at correct times
- [ ] Fix notification dismissal

## Acceptance Criteria
- All notifications show correct messages
- Notifications are properly categorized
- Notifications can be dismissed" \
  --label "bug,notifications,priority-high"

gh issue create \
  --title "[BUG] Fix Geolocation Feature" \
  --body "## Description
The get location feature is not working consistently.

## Tasks
- [ ] Debug geolocation API calls
- [ ] Add error handling for denied permissions
- [ ] Add fallback for unsupported browsers
- [ ] Improve accuracy settings
- [ ] Add loading state during location fetch
- [ ] Store location data properly

## Acceptance Criteria
- Location fetching works reliably
- Users see clear error messages when it fails
- Fallback options available" \
  --label "bug,geolocation,priority-medium"

gh issue create \
  --title "[BUG] Fix Terrain (Map) Tab Active State and Display Real Data" \
  --body "## Description
The Terrain tab doesn't show as active when opened. Also need to display real client data on the map.

## Tasks
- [ ] Fix active state CSS for Terrain tab
- [ ] Use real client location data on map
- [ ] Display purchasing volumes on map
- [ ] Add time filtering (week/month)

## Acceptance Criteria
- Tab shows as active when selected
- Map displays real client positions
- Purchase volumes are visualized" \
  --label "bug,ui,priority-medium"

gh issue create \
  --title "[BUG] Fix Rapport Tab Active State and Add Archive Mode" \
  --body "## Description
Fix the Rapport tab active state and add report archiving functionality.

## Tasks
- [ ] Fix active state for Rapport tab
- [ ] Design archive confirmation modal
- [ ] Implement archive functionality
- [ ] Add archived reports view

## Acceptance Criteria
- Tab shows as active when selected
- Users can archive reports with confirmation
- Archived reports are accessible" \
  --label "bug,feature,priority-medium"

gh issue create \
  --title "[BUG] Fix Client Tab Active State in Admin" \
  --body "## Description
The Client tab doesn't show as active when on the clients page.

## Tasks
- [ ] Fix active state detection for Client tab
- [ ] Update sidenav logic

## Acceptance Criteria
- Client tab shows as active when selected" \
  --label "bug,ui,priority-low"

# ===========================================
# Feature Issues
# ===========================================

echo "✨ Creating Feature Issues..."

gh issue create \
  --title "[FEATURE] Update 'Ajouter Stockeur' Modal" \
  --body "## Description
Update the add stocker modal to remove unnecessary fields.

## Tasks
- [ ] Remove vendor/client dropdown (only stockers)
- [ ] Replace email with phone number
- [ ] Make email optional
- [ ] Update form validation

## Acceptance Criteria
- Modal shows only relevant fields
- Phone number is primary contact
- Email is optional" \
  --label "feature,ui,priority-medium"

gh issue create \
  --title "[FEATURE] Add WhatsApp Support Link" \
  --body "## Description
Add a WhatsApp link for customer support.

## Tasks
- [ ] Add WhatsApp icon to support section
- [ ] Configure WhatsApp link with pre-filled message
- [ ] Add to sidebar or footer

## WhatsApp Link Format
https://wa.me/243XXXXXXXXX?text=Bonjour,%20j'ai%20besoin%20d'aide%20avec%20AirtFast

## Acceptance Criteria
- WhatsApp link opens WhatsApp with support number
- Pre-filled message for context" \
  --label "feature,support,priority-low"

# ===========================================
# Code Quality Issues
# ===========================================

echo "🧹 Creating Code Quality Issues..."

gh issue create \
  --title "[REFACTOR] Standardize Naming Conventions" \
  --body "## Description
Standardize all route names, function names, and file names. Use English for all code.

## Tasks
- [ ] Audit all route names
- [ ] Audit all function names
- [ ] Create naming convention document
- [ ] Rename routes consistently
- [ ] Rename functions consistently
- [ ] Update all references
- [ ] Update templates

## Naming Convention
\`\`\`
Routes: /clients, /sales, /stock-purchases, /reports
Functions: get_clients(), create_sale(), update_stock()
Templates: clients.html, sales.html, edit_sale.html
\`\`\`

## Acceptance Criteria
- Consistent English naming throughout
- No mixed French/English
- All references updated" \
  --label "refactor,code-quality,priority-medium"

gh issue create \
  --title "[REFACTOR] Clean Up and Organize Code" \
  --body "## Description
General code cleanup and organization.

## Tasks
- [ ] Remove unused imports
- [ ] Remove dead code
- [ ] Add proper docstrings
- [ ] Organize imports (standard, third-party, local)
- [ ] Add type hints where appropriate
- [ ] Fix linting errors

## Acceptance Criteria
- Code passes linting
- All files properly documented
- No unused code" \
  --label "refactor,code-quality,priority-medium"

gh issue create \
  --title "[REFACTOR] Improve Flask CLI Commands for Production" \
  --body "## Description
Evaluate and improve the initialization CLI commands for production.

## Current Commands
\`\`\`bash
flask setup create-superadmin
flask setup init-stock
flask setup seed-reports --date 2025-11-11
flask db init
flask db migrate -m 'Initial migration.'
flask db upgrade
\`\`\`

## Tasks
- [ ] Create single initialization command
- [ ] Add idempotent checks (don't duplicate data)
- [ ] Add production safety checks
- [ ] Document all CLI commands
- [ ] Add rollback capabilities

## Acceptance Criteria
- Single command for full setup
- Safe to run multiple times
- Clear documentation" \
  --label "infrastructure,cli,priority-medium"

echo ""
echo "✅ All issues created successfully!"
echo ""
echo "View your issues at: gh issue list"