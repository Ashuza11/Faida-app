"""
Faida App Database Models - Multi-Tenant Architecture

Key Changes for Multi-Tenant:
- Stock is now per-vendeur (each business has its own inventory)
- Stockeurs are linked to their vendeur (employer)
- Phone number is primary identifier for login
- Email is optional

Data Isolation:
- PLATFORM_ADMIN: Can see all data (for support)
- VENDEUR: Can only see their own business data
- STOCKEUR: Can only see their vendeur's data
"""

from datetime import datetime, date, timezone
from typing import Optional, List
from enum import Enum as PyEnum
from flask_login import UserMixin
from apps import db
from hashlib import md5
from werkzeug.security import generate_password_hash, check_password_hash
import sqlalchemy as sa
import sqlalchemy.orm as so
from decimal import Decimal
import re
import secrets


# ===========================================
# Enums
# ===========================================

class RoleType(PyEnum):
    """
    User roles in the system.

    PLATFORM_ADMIN: Platform owner (you). Can see all businesses for support.
    VENDEUR: Business owner. Admin of their own business only.
    STOCKEUR: Employee/salesperson. Works for one vendeur.
    """
    PLATFORM_ADMIN = "platform_admin"
    VENDEUR = "vendeur"
    STOCKEUR = "stockeur"


class BusinessType(PyEnum):
    """Operational model for an independently accounted business."""
    RETAIL = "retail"
    WHOLESALE = "wholesale"


class BusinessApprovalStatus(PyEnum):
    """Platform approval required before a wholesale ledger can operate."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CurrencyCode(PyEnum):
    """Supported business ledger currencies."""
    CDF = "CDF"
    USD = "USD"


class MembershipRole(PyEnum):
    """A user's authority inside one business."""
    OWNER = "owner"
    STOCKEUR = "stockeur"


class PriceOperation(PyEnum):
    PURCHASE = "purchase"
    SALE = "sale"


class PaymentAllocationKind(PyEnum):
    CURRENT_SALE = "current_sale"
    PRIOR_DEBT = "prior_debt"


class TransactionStatus(PyEnum):
    ACTIVE = "active"
    REVERSED = "reversed"


class CashOutflowCategory(PyEnum):
    """Categories for cash outflows."""
    PURCHASE_AIRTIME = "Achat Stock"
    OPERATING_EXPENSE = "Frais de Fonctionnement"
    SALARY = "Salaire"
    RENT = "Restoration"
    OTHER = "Autre"


class CashInflowCategory(PyEnum):
    """Categories for cash inflows."""
    SALE_COLLECTION = "Encaissement Vente"
    OTHER = "Autre Entrée"


class NetworkType(PyEnum):
    """Mobile network operators in DRC."""
    AIRTEL = "airtel"
    AFRICEL = "africel"
    ORANGE = "orange"
    VODACOM = "vodacom"


# ===========================================
# Helper Functions
# ===========================================

def normalize_phone(phone: str) -> str:
    """
    Normalize phone number to consistent +243XXXXXXXXX format.

    Accepts:
    - 0812345678 (local format)
    - 243812345678 (without +)
    - +243812345678 (international format)

    Returns: +243812345678
    """
    if not phone:
        return phone

    # Remove spaces, dashes, parentheses
    phone = ''.join(c for c in phone if c.isdigit() or c == '+')

    # Handle different formats
    if phone.startswith('0'):
        phone = '+243' + phone[1:]
    elif phone.startswith('243') and not phone.startswith('+'):
        phone = '+' + phone
    elif not phone.startswith('+'):
        phone = '+243' + phone

    return phone


def validate_drc_phone(phone: str) -> bool:
    """
    Validate DRC phone number.

    Valid formats after normalization: +243XXXXXXXXX (12 digits total after +)
    Valid prefixes: 81-85 (Vodacom), 89/99 (Airtel), 90/91/97/98 (Orange), 80/86-88 (Africell)
    """
    normalized = normalize_phone(phone)

    if not normalized:
        return False

    # Check format: +243 followed by 9 digits
    pattern = r'^\+243[0-9]{9}$'
    if not re.match(pattern, normalized):
        return False

    # Check valid prefix (digit 4 and 5 after +243)
    prefix = normalized[4:6]
    valid_prefixes = [
        '81', '82', '83', '84', '85',  # Vodacom
        '89', '99',                     # Airtel
        '90', '91', '97', '98',        # Orange
        '80', '86', '87', '88',        # Africell
    ]

    return prefix in valid_prefixes


# ===========================================
# Invite Code Model (for controlled registration)
# ===========================================

class InviteCode(db.Model):
    """
    Invite codes for controlled vendeur registration.
    Platform admin generates codes, vendeurs use them to register.
    """
    __tablename__ = "invite_codes"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    code: so.Mapped[str] = so.mapped_column(
        sa.String(32), unique=True, nullable=False, index=True
    )

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Who created this code (platform admin)
    created_by_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )

    # Who used this code (the new vendeur)
    used_by_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )

    used_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # Optional: expiration date
    expires_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    is_active: so.Mapped[bool] = so.mapped_column(default=True)

    @property
    def is_valid(self) -> bool:
        """Check if code is still valid (not used, not expired, active)."""
        if not self.is_active:
            return False
        if self.used_by_id is not None:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True

    def __repr__(self) -> str:
        status = "valid" if self.is_valid else "used/expired"
        return f"<InviteCode {self.code} ({status})>"


# ===========================================
# User Model
# ===========================================

class User(db.Model, UserMixin):
    """
    User model with phone-first authentication and multi-tenant support.

    Phone number is the primary identifier for login.
    Email is optional (primarily for platform admins).

    For STOCKEUR users, vendeur_id links them to their employer.
    """
    __tablename__ = "users"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Username (display name)
    username: so.Mapped[str] = so.mapped_column(
        sa.String(64), index=True, unique=True, nullable=False
    )

    # Phone number - PRIMARY IDENTIFIER for login
    phone: so.Mapped[str] = so.mapped_column(
        sa.String(20), unique=True, nullable=False, index=True
    )

    # Email - OPTIONAL (for platform admins or those who want email features)
    email: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(120), unique=True, nullable=True
    )

    password_hash: so.Mapped[str] = so.mapped_column(
        sa.String(256), nullable=False
    )

    role: so.Mapped[RoleType] = so.mapped_column(
        sa.Enum(RoleType), nullable=False, default=RoleType.VENDEUR
    )

    # For STOCKEUR: which vendeur do they work for?
    # For VENDEUR/PLATFORM_ADMIN: this is NULL
    vendeur_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )

    # Legacy field - who created this user (kept for backward compatibility)
    created_by: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )

    last_login: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    is_active: so.Mapped[bool] = so.mapped_column(default=True)

    # Personal API token — used by Android TWA to authenticate SMS ingest calls
    api_token: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(64), nullable=True, unique=True, index=True
    )

    # Relationships

    # Self-referential: vendeur -> their stockeurs
    stockeurs: so.Mapped[List["User"]] = so.relationship(
        "User",
        foreign_keys=[vendeur_id],
        backref=so.backref("employer", remote_side=[id]),
        lazy="dynamic"
    )

    # Vendeur's clients (only for VENDEUR role)
    clients: so.Mapped[List["Client"]] = so.relationship(
        back_populates="vendeur",
        foreign_keys="[Client.vendeur_id]",
        cascade="all, delete-orphan"
    )

    # Vendeur's stock items (only for VENDEUR role)
    stock_items: so.Mapped[List["Stock"]] = so.relationship(
        back_populates="vendeur",
        foreign_keys="[Stock.vendeur_id]",
        cascade="all, delete-orphan"
    )

    # Sales made by this user (as the seller)
    sales: so.Mapped[List["Sale"]] = so.relationship(
        back_populates="seller",
        foreign_keys="[Sale.seller_id]",
    )

    # Stock purchases made by this user
    stock_purchases_made: so.Mapped[List["StockPurchase"]] = so.relationship(
        back_populates="purchased_by",
        foreign_keys="[StockPurchase.purchased_by_id]",
        lazy="dynamic",
    )

    # Cash flows recorded by this user
    cash_inflows_recorded: so.Mapped[List["CashInflow"]] = so.relationship(
        back_populates="recorded_by",
        foreign_keys="[CashInflow.recorded_by_id]"
    )
    cash_outflows_recorded: so.Mapped[List["CashOutflow"]] = so.relationship(
        back_populates="recorded_by",
        foreign_keys="[CashOutflow.recorded_by_id]"
    )

    # Opening balances set by this vendeur
    opening_balances: so.Mapped[List["StockOpeningBalance"]] = so.relationship(
        back_populates="vendeur",
        foreign_keys="[StockOpeningBalance.vendeur_id]",
        cascade="all, delete-orphan",
    )

    owned_businesses: so.Mapped[List["Business"]] = so.relationship(
        back_populates="owner",
        foreign_keys="[Business.owner_user_id]",
        cascade="all, delete-orphan",
    )
    business_memberships: so.Mapped[List["BusinessMembership"]] = so.relationship(
        back_populates="user",
        foreign_keys="[BusinessMembership.user_id]",
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str) -> None:
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify a password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def set_phone(self, phone: str) -> None:
        """Normalize and set the user's phone number."""
        self.phone = normalize_phone(phone)

    def get_or_create_api_token(self) -> str:
        """Return the existing API token, generating and saving one if absent."""
        if not self.api_token:
            from apps import db
            self.api_token = secrets.token_urlsafe(32)
            db.session.add(self)
            db.session.commit()
        return self.api_token

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role.value})>"

    def avatar(self, size: int = 80) -> str:
        """Get Gravatar URL for user."""
        identifier = self.email or f"{self.phone}@airtfast.local"
        digest = md5(identifier.lower().encode("utf-8")).hexdigest()
        return f"https://www.gravatar.com/avatar/{digest}?d=identicon&s={size}"

    @property
    def display_phone(self) -> str:
        """Format phone number for display: +243 81 234 5678"""
        if not self.phone:
            return ""
        phone = self.phone
        if len(phone) == 13 and phone.startswith('+243'):
            return f"{phone[:4]} {phone[4:6]} {phone[6:9]} {phone[9:]}"
        return phone

    @property
    def is_platform_admin(self) -> bool:
        """Check if user is platform admin."""
        return self.role == RoleType.PLATFORM_ADMIN

    @property
    def is_vendeur(self) -> bool:
        """Check if user is a vendeur (business owner)."""
        return self.role == RoleType.VENDEUR

    @property
    def is_stockeur(self) -> bool:
        """Check if user is a stockeur (employee)."""
        return self.role == RoleType.STOCKEUR

    @property
    def business_vendeur_id(self) -> int:
        """
        Get the vendeur_id for this user's business context.
        - VENDEUR: returns their own ID
        - STOCKEUR: returns their employer's ID
        - PLATFORM_ADMIN: returns None (they can see all)
        """
        if self.role == RoleType.VENDEUR:
            return self.id
        elif self.role == RoleType.STOCKEUR:
            return self.vendeur_id
        return None  # Platform admin

    def can_access_vendeur_data(self, target_vendeur_id: int) -> bool:
        """Check if this user can access data belonging to a specific vendeur."""
        if self.role == RoleType.PLATFORM_ADMIN:
            return True  # Platform admin can access all
        return self.business_vendeur_id == target_vendeur_id


class Business(db.Model):
    """An independent inventory and accounting ledger owned by a user."""
    __tablename__ = "businesses"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    business_type: so.Mapped[BusinessType] = so.mapped_column(
        sa.Enum(BusinessType), nullable=False, default=BusinessType.RETAIL
    )
    currency_code: so.Mapped[CurrencyCode] = so.mapped_column(
        sa.Enum(CurrencyCode), nullable=False, default=CurrencyCode.CDF
    )
    owner_user_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False, index=True
    )
    approval_status: so.Mapped[BusinessApprovalStatus] = so.mapped_column(
        sa.Enum(BusinessApprovalStatus),
        nullable=False,
        default=BusinessApprovalStatus.APPROVED,
    )
    approved_by_user_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    approved_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    is_active: so.Mapped[bool] = so.mapped_column(default=True, nullable=False)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    owner: so.Mapped[User] = so.relationship(
        back_populates="owned_businesses", foreign_keys=[owner_user_id]
    )
    memberships: so.Mapped[List["BusinessMembership"]] = so.relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    price_presets: so.Mapped[List["PricePreset"]] = so.relationship(
        back_populates="business", cascade="all, delete-orphan"
    )

    @property
    def currency_symbol(self) -> str:
        return "$" if self.currency_code == CurrencyCode.USD else "FC"

    @property
    def allows_stockeurs(self) -> bool:
        return self.business_type == BusinessType.RETAIL


class BusinessMembership(db.Model):
    """Explicit access granted by a business owner to a user."""
    __tablename__ = "business_memberships"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    business_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: so.Mapped[MembershipRole] = so.mapped_column(
        sa.Enum(MembershipRole), nullable=False
    )
    is_active: so.Mapped[bool] = so.mapped_column(default=True, nullable=False)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    business: so.Mapped[Business] = so.relationship(back_populates="memberships")
    user: so.Mapped[User] = so.relationship(back_populates="business_memberships")

    __table_args__ = (
        sa.UniqueConstraint("business_id", "user_id", name="_business_user_membership_uc"),
    )


class PricePreset(db.Model):
    """A business-owned purchase or sale rate shown as a simple choice."""
    __tablename__ = "price_presets"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    business_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    operation: so.Mapped[PriceOperation] = so.mapped_column(
        sa.Enum(PriceOperation), nullable=False
    )
    label: so.Mapped[str] = so.mapped_column(sa.String(80), nullable=False)
    unit_price: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False
    )
    ratio_amount: so.Mapped[Optional[Decimal]] = so.mapped_column(
        sa.Numeric(24, 12), nullable=True
    )
    ratio_units: so.Mapped[Optional[Decimal]] = so.mapped_column(
        sa.Numeric(24, 12), nullable=True
    )
    is_default: so.Mapped[bool] = so.mapped_column(default=False, nullable=False)
    is_active: so.Mapped[bool] = so.mapped_column(default=True, nullable=False)
    display_order: so.Mapped[int] = so.mapped_column(default=0, nullable=False)

    business: so.Mapped[Business] = so.relationship(back_populates="price_presets")

    __table_args__ = (
        sa.CheckConstraint(
            "(ratio_amount IS NULL AND ratio_units IS NULL) OR "
            "(ratio_amount > 0 AND ratio_units > 0)",
            name="_price_preset_complete_ratio_ck",
        ),
    )


# ===========================================
# Client Model
# ===========================================

class Client(db.Model):
    """
    Client/Customer model with location tracking.
    Clients belong to a vendeur's business.
    """
    __tablename__ = "clients"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)

    # Phone numbers per network
    phone_airtel: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_africel: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_orange: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    phone_vodacom: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))

    # Location
    address: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    gps_lat: so.Mapped[Optional[float]] = so.mapped_column()
    gps_long: so.Mapped[Optional[float]] = so.mapped_column()

    is_active: so.Mapped[bool] = so.mapped_column(default=True)

    # Which vendeur owns this client
    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )
    vendeur: so.Mapped[User] = so.relationship(
        back_populates="clients",
        foreign_keys=[vendeur_id]
    )

    # Sales to this client
    sales: so.Mapped[List["Sale"]] = so.relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Client {self.name}>"

    @property
    def primary_phone(self) -> Optional[str]:
        """Get the first available phone number."""
        return (self.phone_vodacom or self.phone_airtel or
                self.phone_orange or self.phone_africel)

    @property
    def has_location(self) -> bool:
        """Check if client has GPS coordinates."""
        return self.gps_lat is not None and self.gps_long is not None


# ===========================================
# Stock Model (NOW PER-VENDEUR)
# ===========================================

class Stock(db.Model):
    """
    Stock inventory for each network - NOW PER VENDEUR.
    Each vendeur has their own stock for each network.
    """
    __tablename__ = "stock"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    # Which vendeur owns this stock
    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )
    vendeur: so.Mapped[User] = so.relationship(
        back_populates="stock_items",
        foreign_keys=[vendeur_id]
    )

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )

    balance = db.Column(
        db.Numeric(precision=12, scale=2),
        default=Decimal("0.00"),
        nullable=False
    )

    # Each vendeur sets their own prices
    buying_price_per_unit: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("0.94")
    )
    selling_price_per_unit: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("1.00")
    )
    inventory_value: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("0.00")
    )
    average_cost_per_unit: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("0.00")
    )

    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Purchases of this stock
    purchases: so.Mapped[List["StockPurchase"]] = so.relationship(
        back_populates="stock_item", cascade="all, delete-orphan"
    )

    # Unique constraint: one stock record per network per vendeur
    __table_args__ = (
        sa.UniqueConstraint('business_id', 'network',
                            name='_business_network_uc'),
    )

    def __repr__(self) -> str:
        return f"<Stock {self.network.value} for Vendeur #{self.vendeur_id}: {self.balance} units>"

    @property
    def margin(self) -> Decimal:
        """Calculate profit margin per unit."""
        return self.selling_price_per_unit - self.buying_price_per_unit

    @property
    def margin_percentage(self) -> float:
        """Calculate profit margin as percentage."""
        if self.buying_price_per_unit == 0:
            return 0.0
        return float((self.margin / self.buying_price_per_unit) * 100)


# ===========================================
# StockPurchase Model
# ===========================================

class StockPurchase(db.Model):
    """Record of stock purchases."""
    __tablename__ = "stock_purchases"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    # Who made this purchase
    purchased_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    purchased_by: so.Mapped["User"] = so.relationship(
        back_populates="stock_purchases_made",
        foreign_keys=[purchased_by_id]
    )

    # Which stock item was purchased
    stock_item_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("stock.id"), nullable=False
    )
    stock_item: so.Mapped["Stock"] = so.relationship(
        back_populates="purchases")

    price_preset_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("price_presets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    price_preset: so.Mapped[Optional["PricePreset"]] = so.relationship()

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )

    buying_price_at_purchase: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(precision=24, scale=12), nullable=False, default=Decimal("0.00")
    )
    selling_price_at_purchase: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False
    )
    actual_total_cost: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("0.00")
    )

    amount_purchased: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False)

    purchase_date: so.Mapped[date] = so.mapped_column(
        sa.Date, nullable=False, default=date.today, index=True
    )
    status: so.Mapped[TransactionStatus] = so.mapped_column(
        sa.Enum(TransactionStatus), nullable=False, default=TransactionStatus.ACTIVE
    )
    reversed_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    reversed_by_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    reversal_reason: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(255), nullable=True
    )

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<StockPurchase {self.network.value} - {self.amount_purchased} units>"

    @property
    def total_cost(self) -> Decimal:
        """Return the immutable exact cost captured when the purchase occurred."""
        return self.actual_total_cost

    @property
    def vendeur_id(self) -> int:
        """Get the vendeur_id through the stock item."""
        return self.stock_item.vendeur_id if self.stock_item else None


# ===========================================
# StockOpeningBalance Model
# ===========================================

class StockOpeningBalance(db.Model):
    """
    Manually set opening (initial) airtime balance for a given network/date/vendeur.
    Takes highest priority in daily report initial-stock calculation,
    overriding the automatic reverse-calculation and archive fallback.
    """
    __tablename__ = "stock_opening_balances"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False, index=True
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )
    vendeur: so.Mapped["User"] = so.relationship(
        foreign_keys=[vendeur_id],
        back_populates="opening_balances",
    )

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )

    balance_date: so.Mapped[date] = so.mapped_column(
        sa.Date(), nullable=False, index=True
    )

    quantity: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )

    set_by_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    set_by: so.Mapped[Optional["User"]] = so.relationship(
        foreign_keys=[set_by_id]
    )

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "vendeur_id", "network", "balance_date",
            name="_opening_balance_vendeur_network_date_uc"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<StockOpeningBalance {self.network.name} "
            f"{self.balance_date} vendeur#{self.vendeur_id}: {self.quantity}>"
        )


# ===========================================
# Sale Model
# ===========================================

class Sale(db.Model):
    """Sales transaction record."""
    __tablename__ = "sales"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # The business date this sale belongs to (set by user, defaults to today).
    # Separate from created_at so that late entries (recorded the next day) are
    # still counted under the correct day when archiving reports.
    sale_date: so.Mapped[date] = so.mapped_column(
        sa.Date,
        nullable=False,
        default=date.today,
        index=True,
    )

    # Who made this sale (vendeur or stockeur)
    seller_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    seller: so.Mapped[User] = so.relationship(
        back_populates="sales",
        foreign_keys=[seller_id]
    )

    # Which vendeur's business does this sale belong to
    # (redundant for vendeurs, but needed for stockeur sales)
    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )

    # Can be linked to a registered client OR use ad-hoc name
    client_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("clients.id"), nullable=True
    )
    client: so.Mapped[Optional[Client]] = so.relationship(
        back_populates="sales")
    client_name_adhoc: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(128), nullable=True
    )

    # Financial details
    total_amount_due: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    cash_paid: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    debt_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    initial_cash_paid: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    status: so.Mapped[TransactionStatus] = so.mapped_column(
        sa.Enum(TransactionStatus), nullable=False, default=TransactionStatus.ACTIVE
    )
    reversed_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    reversed_by_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    reversal_reason: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(255), nullable=True
    )

    # Relationships
    sale_items: so.Mapped[List["SaleItem"]] = so.relationship(
        back_populates="sale", cascade="all, delete-orphan"
    )
    cash_inflows: so.Mapped[List["CashInflow"]] = so.relationship(
        back_populates="sale", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        client_info = self.client.name if self.client else self.client_name_adhoc
        return f"<Sale #{self.id} to {client_info}>"

    @property
    def client_display_name(self) -> str:
        """Get client name for display."""
        if self.client:
            return self.client.name
        return self.client_name_adhoc or "Client inconnu"

    @property
    def is_fully_paid(self) -> bool:
        """Check if sale is fully paid."""
        return self.debt_amount <= Decimal("0.00")


# ===========================================
# SaleItem Model
# ===========================================

class SaleItem(db.Model):
    """Individual items in a sale."""
    __tablename__ = "sale_items"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    sale_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("sales.id"), nullable=False
    )
    sale: so.Mapped[Sale] = so.relationship(back_populates="sale_items")

    price_preset_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("price_presets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    price_preset: so.Mapped[Optional["PricePreset"]] = so.relationship()

    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    quantity: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    price_per_unit_applied: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False
    )
    subtotal: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False
    )
    cost_per_unit_snapshot: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("0.00")
    )
    cost_total: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("0.00")
    )
    margin_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False, default=Decimal("0.00")
    )
    is_cost_estimated: so.Mapped[bool] = so.mapped_column(
        nullable=False, default=False
    )

    def __repr__(self) -> str:
        return f"<SaleItem {self.quantity}x {self.network.value}>"


# ===========================================
# SaleItemHistory Model
# ===========================================

class SaleItemHistory(db.Model):
    """Snapshot of sale items before an edit or delete.

    Written immediately before SaleItems are mutated so that discrepancies
    (e.g. airtime sent then sale edited) can be reconstructed after the fact.
    """
    __tablename__ = "sale_item_history"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    # When the snapshot was taken (≈ time of edit/delete)
    snapshot_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # The sale this snapshot belongs to (kept even after the sale is deleted)
    sale_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("sales.id", ondelete="SET NULL"),
        nullable=True,
    )

    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )

    # Who triggered the change
    changed_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )

    # What triggered the snapshot
    action: so.Mapped[str] = so.mapped_column(
        sa.String(10), nullable=False
    )  # 'edit' | 'delete'

    # The item state at snapshot time
    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )
    quantity: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    price_per_unit_applied: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(24, 12), nullable=False
    )
    subtotal: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<SaleItemHistory sale={self.sale_id} {self.action} "
            f"{self.quantity}x {self.network.value}>"
        )


# ===========================================
# Cash Flow Models
# ===========================================

class CashOutflow(db.Model):
    """Cash outflows (expenses) - per vendeur."""
    __tablename__ = "cash_outflows"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # The business date this expense belongs to (set by user, defaults to today).
    expense_date: so.Mapped[date] = so.mapped_column(
        sa.Date,
        nullable=False,
        default=date.today,
        index=True,
    )

    # Which vendeur's business
    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )

    recorded_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    recorded_by: so.Mapped["User"] = so.relationship(
        back_populates="cash_outflows_recorded",
        foreign_keys=[recorded_by_id]
    )

    amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False
    )
    category: so.Mapped[CashOutflowCategory] = so.mapped_column(
        sa.Enum(CashOutflowCategory), nullable=False
    )
    description: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(255), nullable=True
    )

    def __repr__(self) -> str:
        return f"<CashOutflow {self.amount} - {self.category.value}>"


class PaymentEvent(db.Model):
    """One customer payment before it is split across sale debts."""
    __tablename__ = "payment_events"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )
    client_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("clients.id"), nullable=False, index=True
    )
    source_sale_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("sales.id"), nullable=True, index=True
    )
    recorded_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    amount: so.Mapped[Decimal] = so.mapped_column(sa.Numeric(12, 2), nullable=False)
    payment_date: so.Mapped[date] = so.mapped_column(sa.Date, nullable=False, index=True)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    allocations: so.Mapped[List["CashInflow"]] = so.relationship(
        back_populates="payment_event", cascade="all, delete-orphan"
    )


class CashInflow(db.Model):
    """Cash inflows (receipts) - per vendeur."""
    __tablename__ = "cash_inflows"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Which vendeur's business
    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )
    payment_event_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("payment_events.id"), nullable=True, index=True
    )
    payment_event: so.Mapped[Optional[PaymentEvent]] = so.relationship(
        back_populates="allocations"
    )

    recorded_by_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    recorded_by: so.Mapped["User"] = so.relationship(
        back_populates="cash_inflows_recorded",
        foreign_keys=[recorded_by_id]
    )

    amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False
    )
    category: so.Mapped[CashInflowCategory] = so.mapped_column(
        sa.Enum(CashInflowCategory),
        nullable=False,
        default=CashInflowCategory.SALE_COLLECTION,
    )
    allocation_kind: so.Mapped[Optional[PaymentAllocationKind]] = so.mapped_column(
        sa.Enum(PaymentAllocationKind), nullable=True
    )
    description: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(255), nullable=True
    )

    # The business date this payment belongs to (set by user, defaults to today).
    # Separate from created_at so late entries are counted under the correct day.
    payment_date: so.Mapped[date] = so.mapped_column(
        sa.Date,
        nullable=False,
        default=date.today,
        index=True,
    )

    # Link to sale (for payment collections)
    sale_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("sales.id"), nullable=True
    )
    sale: so.Mapped[Optional["Sale"]] = so.relationship(
        back_populates="cash_inflows")

    def __repr__(self) -> str:
        return f"<CashInflow {self.amount} - {self.category.value}>"


# ===========================================
# Report Models (NOW PER-VENDEUR)
# ===========================================

class DailyStockReport(db.Model):
    """Daily stock report per network per vendeur."""
    __tablename__ = "daily_stock_reports"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    # Which vendeur's report
    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )

    report_date: so.Mapped[date] = so.mapped_column(
        sa.Date, nullable=False, index=True
    )
    network: so.Mapped[NetworkType] = so.mapped_column(
        sa.Enum(NetworkType), nullable=False
    )

    initial_stock_balance: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    purchased_stock_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    sold_stock_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    final_stock_balance: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    virtual_value: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    debt_amount: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    __table_args__ = (
        sa.UniqueConstraint("vendeur_id", "report_date",
                            "network", name="_vendeur_report_date_network_uc"),
    )

    def __repr__(self) -> str:
        return f"<DailyStockReport {self.report_date} - {self.network.name} for Vendeur #{self.vendeur_id}>"


class DailyOverallReport(db.Model):
    """Daily overall report (all networks combined) per vendeur."""
    __tablename__ = "daily_overall_reports"

    id: so.Mapped[int] = so.mapped_column(primary_key=True, autoincrement=True)

    # Which vendeur's report
    vendeur_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey("users.id"), nullable=False
    )
    business_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("businesses.id"), nullable=True, index=True
    )

    report_date: so.Mapped[date] = so.mapped_column(
        sa.Date, nullable=False, index=True
    )

    total_initial_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_purchased_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_sold_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_final_stock: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_virtual_value: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_debts: so.Mapped[Decimal] = so.mapped_column(
        sa.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    __table_args__ = (
        sa.UniqueConstraint("vendeur_id", "report_date",
                            name="_vendeur_report_date_uc"),
    )

    def __repr__(self) -> str:
        return f"<DailyOverallReport {self.report_date} for Vendeur #{self.vendeur_id}>"


# ===========================================
# Helper Functions
# ===========================================

def create_stock_for_vendeur(vendeur_id: int,
                             buying_price: Decimal = Decimal("0.94"),
                             selling_price: Decimal = Decimal("1.00")) -> List[Stock]:
    """
    Create stock items for all networks for a new vendeur.
    Called when a new vendeur account is created.

    Returns list of created Stock objects.
    """
    stocks = []
    for network in NetworkType:
        stock = Stock(
            vendeur_id=vendeur_id,
            network=network,
            balance=Decimal("0.00"),
            buying_price_per_unit=buying_price,
            selling_price_per_unit=selling_price,
        )
        db.session.add(stock)
        stocks.append(stock)
    return stocks


def get_vendeur_stock(vendeur_id: int, network: NetworkType = None):
    """
    Get stock for a vendeur.
    If network is specified, return single Stock object.
    Otherwise return all stocks for the vendeur.
    """
    if network:
        return Stock.query.filter_by(vendeur_id=vendeur_id, network=network).first()
    return Stock.query.filter_by(vendeur_id=vendeur_id).all()
